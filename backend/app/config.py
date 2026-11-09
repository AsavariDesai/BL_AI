"""Runtime configuration and project paths. No cloud services."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:  # optional, only needed for local .env loading
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:  # pragma: no cover
    pass

BACKEND_DIR = Path(__file__).resolve().parent.parent          # .../BL-AI/backend
PROJECT_DIR = BACKEND_DIR.parent                              # .../BL-AI

# BL_DATA_DIR overrides where uploads / the sqlite db / model artifacts live
# (used by tests and by container deployments that mount a data volume).
_data_override = os.getenv("BL_DATA_DIR")
DATA_DIR = Path(_data_override).resolve() if _data_override else (PROJECT_DIR / "data")
UPLOAD_DIR = DATA_DIR / "uploads"
MODEL_DIR = DATA_DIR / "models"
DB_PATH = DATA_DIR / "bl.db"

for _d in (DATA_DIR, UPLOAD_DIR, MODEL_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# Extra origins the API should accept browser requests from, beyond the
# built-in localhost dev ports — e.g. the VDI's hostname when the frontend
# is served separately from the API. Comma-separated, e.g.
# "http://vdi-host:5173,https://bl-ai.internal.example.com".
ALLOWED_ORIGINS: list[str] = [
    o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()
]


@dataclass(frozen=True)
class Settings:
    ocr_backend: str = os.getenv("OCR_BACKEND", "rapidocr")
    ocr_dpi: int = int(os.getenv("OCR_DPI", "200"))
    ocr_lang: str = os.getenv("OCR_LANG", "en")
    extraction_engine: str = os.getenv("EXTRACTION_ENGINE", "rules")
    kie_model_dir: str | None = os.getenv("KIE_MODEL_DIR") or None
    # When set, the API mounts the built frontend (frontend/dist) at "/" so
    # one process serves both the UI and the API on one port. Off by default
    # so `uvicorn --reload` during development doesn't shadow the Vite dev
    # server's routes.
    serve_frontend: bool = os.getenv("SERVE_FRONTEND", "0") == "1"
    # The session cookie's Secure flag — browsers silently drop Secure
    # cookies over plain HTTP, so this must stay off until the deployment is
    # actually served over HTTPS (set COOKIE_SECURE=1 once it is).
    cookie_secure: bool = os.getenv("COOKIE_SECURE", "0") == "1"
    # Bind address/port for the production entrypoint (run_server.py) and the
    # Windows Service wrapper (windows_service.py). Dev keeps using the CLI
    # flags in package.json's dev:api script instead.
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8000"))
    log_level: str = os.getenv("LOG_LEVEL", "info")
    # How many documents the background extraction pool (app/service.py's
    # _EXTRACT_POOL) OCRs/extracts in parallel. Default is CPU-aware but
    # capped at 4 so a modest dev machine doesn't have every core pinned by
    # extraction alone — raise it in backend/.env on a bigger server to
    # actually speed up a large bulk batch (e.g. EXTRACT_WORKERS=8 on an
    # 8-16 vCPU box). Each worker gets its own OCR engine instance
    # (app/ocr.py), so this is also what bounds OCR model memory use.
    extract_workers: int = int(
        os.getenv("EXTRACT_WORKERS", str(max(1, min(4, os.cpu_count() or 1))))
    )


settings = Settings()
