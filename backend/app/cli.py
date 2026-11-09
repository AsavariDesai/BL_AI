"""Command-line test harness for the local extraction pipeline.

    python -m app.cli "../samples/181142608002- SEAWAY BL.pdf"
    python -m app.cli "../samples/HBL-H680557 (1).pdf" --engine rules --json out.json
"""
from __future__ import annotations

import argparse
import os
import uuid
from pathlib import Path


def _resolve(raw: str) -> Path:
    """Accept a path relative to the current dir OR to where the command was
    invoked (npm sets INIT_CWD; scripts/py.mjs runs with cwd=backend/)."""
    p = Path(raw)
    if p.exists():
        return p
    init_cwd = os.environ.get("INIT_CWD")
    if init_cwd and (alt := Path(init_cwd) / raw).exists():
        return alt
    return p

from .config import settings
from .extraction import get_extractor
from .field_catalog import get_field


def _fmt(value: str | None, width: int = 46) -> str:
    text = (value or "").replace("\n", " / ")
    return text if len(text) <= width else text[: width - 3] + "..."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract canonical fields from a BL PDF (local, no cloud).")
    parser.add_argument("pdf", help="Path to a Bill of Lading PDF")
    parser.add_argument("--engine", default=settings.extraction_engine,
                        choices=["rules", "kie"])
    parser.add_argument("--doc-type", default=None,
                        choices=["bill_of_lading", "shipping_bill", "master_bl", "house_bl"])
    parser.add_argument("--json", dest="json_out", help="Write full result JSON here")
    parser.add_argument("--tokens", action="store_true",
                        help="Dump the OCR/text token grid (row by row) and exit — "
                             "paste this to debug a mis-read layout")
    args = parser.parse_args(argv)

    pdf_path = _resolve(args.pdf)
    if not pdf_path.exists():
        parser.error(f"File not found: {args.pdf}")

    if args.tokens:
        from .document import group_rows, load_document

        d = load_document(str(pdf_path))
        for page in d.pages:
            print(f"\n===== PAGE {page.number}  ({'scanned/OCR' if page.is_scanned else 'digital'})"
                  f"  {page.width:.0f}x{page.height:.0f} =====")
            for row in group_rows(page.tokens):
                y = row[0].y0
                cells = " | ".join(f"{t.text}@{t.x0:.0f}" for t in row)
                print(f"y{y:6.0f}  {cells}")
        return 0

    from .classify import detect_doc_type, head_text_from_bytes
    from .db import init_db

    init_db()
    doc_type = args.doc_type or detect_doc_type(head_text_from_bytes(pdf_path.read_bytes()))[0]
    extractor = get_extractor(args.engine)
    result = extractor.extract(str(pdf_path), doc_id=str(uuid.uuid4()), doc_type=doc_type)

    print()
    print(f"File            : {pdf_path.name}")
    print(f"Doc type        : {doc_type}")
    print(f"Engine          : {result.engine}")
    print(f"Detected format : {_fmt(result.detected_format, 58)}")
    print("=" * 80)
    print(f"{'FIELD':<30}{'CONF':>5} {'PG':>3}  VALUE")
    print("-" * 80)
    for fv in result.fields:
        label = get_field(fv.key)["label"]
        print(f"{label:<30}{fv.confidence:>5.2f} {str(fv.page or '-'):>3}  {_fmt(fv.value)}")
    print("-" * 80)
    filled = sum(1 for f in result.fields if f.value)
    print(f"{filled}/{len(result.fields)} fields populated")
    for w in result.warnings:
        print(f"\n! {w}")

    if args.json_out:
        Path(args.json_out).write_text(result.model_dump_json(indent=2), encoding="utf-8")
        print(f"\nWrote {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
