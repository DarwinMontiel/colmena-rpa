"""Punto de entrada: ``rpa-monitor`` (uvicorn)."""

from __future__ import annotations

import os

import uvicorn
from fastapi import FastAPI

from rpa_orchestrator.config import get_settings
from rpa_orchestrator.logging import configure_logging
from rpa_orchestrator.monitor.app import create_app
from rpa_orchestrator.persistence import create_db_engine


def build() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    return create_app(settings, create_db_engine(settings.database_url))


def main() -> None:
    uvicorn.run(
        "rpa_orchestrator.monitor.main:build",
        factory=True,
        host=os.getenv("RPA_MONITOR_HOST", "0.0.0.0"),  # noqa: S104 - se publica tras proxy/contenedor
        port=int(os.getenv("RPA_MONITOR_PORT", "8000")),
        proxy_headers=True,
    )


if __name__ == "__main__":
    main()
