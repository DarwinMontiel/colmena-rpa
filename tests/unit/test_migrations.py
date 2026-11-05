"""La migración de Alembic debe producir exactamente el esquema declarado en ``tables.py``."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from rpa_orchestrator.config import get_settings
from rpa_orchestrator.persistence.tables import metadata

ROOT = Path(__file__).parents[2]


def test_migrations_match_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    url = f"sqlite:///{(tmp_path / 'm.db').as_posix()}"
    monkeypatch.setenv("RPA_DATABASE_URL", url)
    get_settings.cache_clear()
    try:
        cfg = Config(str(ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(ROOT / "alembic"))
        command.upgrade(cfg, "head")

        engine = create_engine(url)
        with engine.connect() as conn:
            diff = compare_metadata(MigrationContext.configure(conn), metadata)
        engine.dispose()
        assert diff == []

        command.downgrade(cfg, "base")
    finally:
        get_settings.cache_clear()
