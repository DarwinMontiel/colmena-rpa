"""Entidades y contratos de mensajes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


def utcnow() -> datetime:
    return datetime.now(UTC)


class TaskStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    RETRYING = "RETRYING"
    DONE = "DONE"
    FAILED = "FAILED"

    @property
    def is_final(self) -> bool:
        return self in {TaskStatus.DONE, TaskStatus.FAILED}


def requeue_allowed(
    status: TaskStatus, updated_at: datetime, now: datetime, pending_stale_after: timedelta
) -> bool:
    """Regla de reproceso manual.

    * ``FAILED``: siempre (el mensaje ya salió de la cola principal).
    * ``PENDING``: solo si lleva más de ``pending_stale_after`` sin cambios. Una tarea PENDING
      reciente casi seguro tiene su mensaje esperando en la cola; republicarla crearía un
      duplicado que dos obreras podrían ejecutar en paralelo.
    * ``RUNNING``, ``RETRYING`` y ``DONE``: nunca.
    """
    if status is TaskStatus.FAILED:
        return True
    return status is TaskStatus.PENDING and now - updated_at >= pending_stale_after


class WorkerState(StrEnum):
    IDLE = "IDLE"
    BUSY = "BUSY"
    STOPPING = "STOPPING"


class TaskMessage(BaseModel):
    """Contrato del mensaje que viaja por RabbitMQ (versionado con ``schema_version``)."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    task_id: UUID = Field(default_factory=uuid4)
    process: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    payload: dict[str, Any] = Field(default_factory=dict)
    attempt: int = Field(default=1, ge=1)
    correlation_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)

    def next_attempt(self) -> TaskMessage:
        return self.model_copy(update={"attempt": self.attempt + 1})

    def to_bytes(self) -> bytes:
        return self.model_dump_json().encode("utf-8")

    @classmethod
    def from_bytes(cls, body: bytes) -> TaskMessage:
        return cls.model_validate_json(body)
