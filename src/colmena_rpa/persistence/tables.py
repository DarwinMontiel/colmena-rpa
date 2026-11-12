"""Esquema de base de datos. Fuente de verdad para Alembic (``alembic/versions``)."""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()

JsonType = JSON().with_variant(JSONB(), "postgresql")

tasks = Table(
    "tasks",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("process", String(64), nullable=False),
    Column("status", String(16), nullable=False),
    Column("payload", JsonType, nullable=False),
    Column("output", JsonType, nullable=True),
    Column("attempts", Integer, nullable=False, default=0),
    Column("last_error", Text, nullable=True),
    Column("correlation_id", String(128), nullable=True),
    Column("worker_id", String(128), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=True),
    Column("finished_at", DateTime(timezone=True), nullable=True),
    Index("ix_tasks_status_process", "status", "process"),
    Index("ix_tasks_finished_at", "finished_at"),
)

task_events = Table(
    "task_events",
    metadata,
    Column(
        "id", BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    ),
    Column("task_id", Uuid, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
    Column("event", String(32), nullable=False),
    Column("attempt", Integer, nullable=False),
    Column("detail", Text, nullable=True),
    Column("worker_id", String(128), nullable=True),
    Column("at", DateTime(timezone=True), nullable=False),
    Index("ix_task_events_task_id", "task_id"),
)

bot_heartbeats = Table(
    "bot_heartbeats",
    metadata,
    Column("worker_id", String(128), primary_key=True),
    Column("hostname", String(128), nullable=False),
    Column("platform", String(64), nullable=False),
    Column("processes", JsonType, nullable=False),
    Column("state", String(16), nullable=False),
    Column("current_task_id", Uuid, nullable=True),
    Column("tasks_ok", Integer, nullable=False, default=0),
    Column("tasks_failed", Integer, nullable=False, default=0),
    Column("version", String(32), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("last_seen", DateTime(timezone=True), nullable=False),
)
