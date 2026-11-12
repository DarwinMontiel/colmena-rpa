from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel

from colmena_rpa.domain.models import TaskStatus, WorkerState


class BotOut(BaseModel):
    worker_id: str
    hostname: str
    platform: str
    processes: list[str]
    state: WorkerState
    health: Literal["ONLINE", "OFFLINE"]
    current_task_id: UUID | None
    tasks_ok: int
    tasks_failed: int
    version: str
    started_at: datetime
    last_seen: datetime
    seconds_since_seen: float


class SummaryOut(BaseModel):
    by_status: dict[str, int]
    by_process: dict[str, dict[str, int]]
    success_rate: float | None
    done_last_hour: int
    failed_last_hour: int
    avg_duration_seconds: float | None
    bots_online: int
    bots_offline: int
    generated_at: datetime


class EventOut(BaseModel):
    event: str
    attempt: int
    detail: str | None
    worker_id: str | None
    at: datetime


class TaskOut(BaseModel):
    id: UUID
    process: str
    status: TaskStatus
    attempts: int
    last_error: str | None
    correlation_id: str | None
    worker_id: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    duration_seconds: float | None


class TaskDetailOut(TaskOut):
    payload: dict[str, Any]
    output: dict[str, Any] | None
    events: list[EventOut]


class RequeueOut(BaseModel):
    task_id: UUID
    status: TaskStatus
