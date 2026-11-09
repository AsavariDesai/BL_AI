"""Production entrypoint — no --reload, no file watcher, one long-lived
worker process (matches the OCR extraction pool, which is deliberately
single-worker too — see app/service.py). Driven by HOST/PORT/LOG_LEVEL in
backend/.env.

Used directly for a manual foreground run:
    backend\\.venv\\Scripts\\python.exe run_server.py

and imported by windows_service.py, which runs the same Uvicorn Server object
inside a Windows Service so it starts on boot and restarts on failure.
"""
from __future__ import annotations

import uvicorn

from app.config import settings


def make_server() -> uvicorn.Server:
    config = uvicorn.Config(
        "app.api:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        reload=False,
        workers=1,
    )
    return uvicorn.Server(config)


if __name__ == "__main__":
    make_server().run()
