from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import StaticPool


def create_db_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        # Una sola conexión compartida: necesario para SQLite en memoria entre hilos.
        return create_engine(
            url, connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
        )
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5, future=True)
