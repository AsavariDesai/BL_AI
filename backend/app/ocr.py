"""Local OCR backends. All run on-box, no network calls.

Each backend takes PNG bytes and returns a list of
``(text, (x0, y0, x1, y1), confidence)`` tuples in *pixel* coordinates.
The caller scales those boxes back into PDF-point space.
"""
from __future__ import annotations

import io
import threading
from typing import Protocol

OcrLine = tuple[str, tuple[float, float, float, float], float]


class OcrBackend(Protocol):
    def read(self, png_bytes: bytes) -> list[OcrLine]: ...


class RapidOcrBackend:
    """PaddleOCR models via onnxruntime. Pure-pip, CPU, no system deps."""

    def __init__(self) -> None:
        from rapidocr_onnxruntime import RapidOCR

        # RapidOCR's own shipped config.yaml defaults intra_op/inter_op
        # threads to -1 (onnxruntime's "use every core") independently for
        # each of its three internal models (detection/classification/
        # recognition) — fine for a single one-off call, but this app now
        # parallelizes across *documents* instead (EXTRACT_WORKERS, see
        # app/service.py's _EXTRACT_POOL and this module's thread-local
        # engine cache). Left at -1, N concurrent OCR calls would each try
        # to claim every CPU core for three separate sessions — serious
        # oversubscription that was measured adding well over a minute to
        # a single two-page document's OCR on an 8-core dev machine, almost
        # entirely thread-pool contention/churn rather than real inference
        # work. Pinned to 1: let the outer worker count be the only
        # parallelism knob.
        self._engine = RapidOCR(intra_op_num_threads=1, inter_op_num_threads=1)

    def read(self, png_bytes: bytes) -> list[OcrLine]:
        import numpy as np
        from PIL import Image

        image = np.array(Image.open(io.BytesIO(png_bytes)).convert("RGB"))
        result, _ = self._engine(image)
        lines: list[OcrLine] = []
        for box, text, score in result or []:
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            lines.append((text, (min(xs), min(ys), max(xs), max(ys)), float(score)))
        return lines


class TesseractBackend:
    """Tesseract 5 via pytesseract. Needs the tesseract binary on PATH."""

    def __init__(self, lang: str = "eng") -> None:
        import pytesseract  # noqa: F401  (import check only)

        self.lang = lang

    def read(self, png_bytes: bytes) -> list[OcrLine]:
        import pytesseract
        from PIL import Image

        image = Image.open(io.BytesIO(png_bytes))
        data = pytesseract.image_to_data(
            image, lang=self.lang, output_type=pytesseract.Output.DICT
        )
        lines: list[OcrLine] = []
        for i, text in enumerate(data["text"]):
            if not text.strip():
                continue
            x, y = data["left"][i], data["top"][i]
            w, h = data["width"][i], data["height"][i]
            raw_conf = data["conf"][i]
            conf = float(raw_conf) / 100.0 if str(raw_conf) not in ("-1", "") else 0.0
            lines.append((text, (x, y, x + w, y + h), conf))
        return lines


# One backend instance per worker thread, not a single shared global one —
# the extraction pool (app/service.py's _EXTRACT_POOL) now runs several
# documents' OCR concurrently, and a RapidOCR instance's onnxruntime
# sessions aren't documented as safe to share across threads the way a
# single session's own .run() calls are. Each engine's ONNX models are only
# ~15MB, so one per thread (a handful, per EXTRACT_WORKERS) costs nothing
# that matters.
_local = threading.local()


def get_ocr_backend(name: str) -> OcrBackend:
    """Lazily construct and cache an OCR backend by name, per thread."""
    cache: dict[str, OcrBackend] = getattr(_local, "cache", None) or {}
    if name in cache:
        return cache[name]

    if name == "rapidocr":
        backend: OcrBackend = RapidOcrBackend()
    elif name == "tesseract":
        backend = TesseractBackend()
    else:
        raise ValueError(f"Unknown OCR backend: {name!r} (expected 'rapidocr' or 'tesseract')")

    cache[name] = backend
    _local.cache = cache
    return backend
