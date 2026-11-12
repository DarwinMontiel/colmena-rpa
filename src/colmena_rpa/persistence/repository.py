"""Repositorios: única capa que conoce SQL. Cada cambio de estado deja un evento de auditoría."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Engine, func, insert, select, update
from sqlalchemy.dialects import postgresql, sqlite

from colmena_rpa.domain.models import (
    TaskMessage,
    TaskStatus,
    WorkerState,
    requeue_allowed,
    utcnow,
)
from colmena_rpa.persistence.tables import bot_heartbeats, task_events, tasks

Clock = Callable[[], datetime]


def _aware(value: datetime | None) -> datetime | None:
    """SQLite devuelve fechas sin zona horaria: se asumen en UTC."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def _dialect_insert(conn: Connection) -> Any:
    return postgresql.insert if conn.dialect.name == "postgresql" else sqlite.insert


@dataclass(frozen=True, slots=True)
class TaskRecord:
    id: UUID
    process: str
    status: TaskStatus
    payload: dict[str, Any]
    output: dict[str, Any] | None
    attempts: int
    last_error: str | None
    correlation_id: str | None
    worker_id: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def duration_seconds(self) -> float | None:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None


@dataclass(frozen=True, slots=True)
class Summary:
    by_status: dict[str, int]
    by_process: dict[str, dict[str, int]]
    done_last_hour: int
    failed_last_hour: int
    avg_duration_seconds: float | None

    @property
    def success_rate(self) -> float | None:
        done = self.by_status.get(TaskStatus.DONE, 0)
        failed = self.by_status.get(TaskStatus.FAILED, 0)
        total = done + failed
        return round(done / total, 4) if total else None


class TaskRepository:
    def __init__(self, engine: Engine, clock: Clock = utcnow) -> None:
        self._engine = engine
        self._clock = clock

    # ---------- escritura ----------
    def register_pending(self, message: TaskMessage) -> bool:
        """Registra la tarea antes de publicarla. Devuelve False si ya existía (idempotente)."""
        now = self._clock()
        with self._engine.begin() as conn:
            stmt = (
                _dialect_insert(conn)(tasks)
                .values(
                    id=message.task_id,
                    process=message.process,
                    status=TaskStatus.PENDING,
                    payload=message.payload,
                    attempts=0,
                    correlation_id=message.correlation_id,
                    created_at=message.created_at,
                    updated_at=now,
                )
                .on_conflict_do_nothing(index_elements=["id"])
                .returning(tasks.c.id)
            )
            # RETURNING y no rowcount: con psycopg 3 + SQLAlchemy 2.1 el rowcount de un
            # INSERT ... ON CONFLICT DO NOTHING no es confiable y toda fila parecía duplicada.
            created = conn.execute(stmt).first() is not None
            if created:
                self._event(conn, message.task_id, "ENQUEUED", 0, None, None)
            return created

    def mark_running(self, message: TaskMessage, worker_id: str) -> bool:
        """Reclama la tarea para esta obrera.

        El ``UPDATE`` es condicional (``status`` no final), así que la verificación y el cambio
        de estado son atómicos: si otra obrera ya la terminó, devuelve ``False`` y el mensaje
        se confirma como duplicado sin ejecutar el bot.
        """
        now = self._clock()
        with self._engine.begin() as conn:
            exists = conn.execute(select(tasks.c.id).where(tasks.c.id == message.task_id)).first()
            if exists is None:
                # Mensaje publicado por un sistema externo sin registro previo.
                conn.execute(
                    insert(tasks).values(
                        id=message.task_id,
                        process=message.process,
                        status=TaskStatus.PENDING,
                        payload=message.payload,
                        attempts=0,
                        correlation_id=message.correlation_id,
                        created_at=message.created_at,
                        updated_at=now,
                    )
                )
            claimed = conn.execute(
                update(tasks)
                .where(
                    tasks.c.id == message.task_id,
                    tasks.c.status.not_in([TaskStatus.DONE, TaskStatus.FAILED]),
                )
                .values(
                    status=TaskStatus.RUNNING,
                    attempts=message.attempt,
                    worker_id=worker_id,
                    started_at=now,
                    finished_at=None,
                    updated_at=now,
                )
            ).rowcount
            if claimed != 1:
                return False
            self._event(conn, message.task_id, "STARTED", message.attempt, None, worker_id)
            return True

    def mark_retrying(self, task_id: UUID, attempt: int, error: str, delay_seconds: int) -> None:
        self._transition(
            task_id,
            TaskStatus.RETRYING,
            attempt,
            event="RETRY_SCHEDULED",
            detail=f"reintento en {delay_seconds}s: {error}",
            values={"last_error": error},
        )

    def mark_done(self, task_id: UUID, attempt: int, output: dict[str, Any]) -> None:
        self._transition(
            task_id,
            TaskStatus.DONE,
            attempt,
            event="COMPLETED",
            detail=None,
            values={"output": output, "finished_at": self._clock(), "last_error": None},
        )

    def mark_failed(self, task_id: UUID, attempt: int, error: str) -> None:
        self._transition(
            task_id,
            TaskStatus.FAILED,
            attempt,
            event="FAILED",
            detail=error,
            values={"last_error": error, "finished_at": self._clock()},
        )

    def requeue(
        self, task_id: UUID, pending_stale_after: timedelta = timedelta(minutes=15)
    ) -> TaskMessage | None:
        """Devuelve a PENDING una tarea FAILED (o PENDING estancada) y retorna el mensaje a
        republicar. ``None`` si la regla de :func:`requeue_allowed` no lo permite."""
        now = self._clock()
        with self._engine.begin() as conn:
            row = (
                conn.execute(select(tasks).where(tasks.c.id == task_id).with_for_update())
                .mappings()
                .first()
            )
            if row is None or not requeue_allowed(
                TaskStatus(row["status"]),
                _aware(row["updated_at"]),  # type: ignore[arg-type]
                now,
                pending_stale_after,
            ):
                return None
            # Guarda optimista (útil en motores sin SELECT ... FOR UPDATE): si otro reproceso
            # cambió la fila entre la lectura y la escritura, no se republica dos veces.
            changed = conn.execute(
                update(tasks)
                .where(
                    tasks.c.id == task_id,
                    tasks.c.status == row["status"],
                    tasks.c.updated_at == row["updated_at"],
                )
                .values(status=TaskStatus.PENDING, updated_at=now, finished_at=None)
            ).rowcount
            if changed != 1:
                return None
            self._event(conn, task_id, "REQUEUED", row["attempts"], "reproceso manual", None)
            return TaskMessage(
                task_id=row["id"],
                process=row["process"],
                payload=row["payload"],
                correlation_id=row["correlation_id"],
            )

    # ---------- lectura ----------
    def get_status(self, task_id: UUID) -> TaskStatus | None:
        with self._engine.connect() as conn:
            value = conn.execute(select(tasks.c.status).where(tasks.c.id == task_id)).scalar()
        return TaskStatus(value) if value else None

    def get(self, task_id: UUID, with_events: bool = True) -> TaskRecord | None:
        with self._engine.connect() as conn:
            row = conn.execute(select(tasks).where(tasks.c.id == task_id)).mappings().first()
            if row is None:
                return None
            events: list[dict[str, Any]] = []
            if with_events:
                events = [
                    {**dict(e), "at": _aware(e["at"])}
                    for e in conn.execute(
                        select(
                            task_events.c.event,
                            task_events.c.attempt,
                            task_events.c.detail,
                            task_events.c.worker_id,
                            task_events.c.at,
                        )
                        .where(task_events.c.task_id == task_id)
                        .order_by(task_events.c.id)
                    ).mappings()
                ]
        return self._record(row, events)

    def search(
        self,
        status: TaskStatus | None = None,
        process: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[TaskRecord]:
        query = select(tasks).order_by(tasks.c.updated_at.desc()).limit(limit).offset(offset)
        if status:
            query = query.where(tasks.c.status == status)
        if process:
            query = query.where(tasks.c.process == process)
        with self._engine.connect() as conn:
            return [self._record(row) for row in conn.execute(query).mappings()]

    def summary(self) -> Summary:
        now = self._clock()
        hour_ago = now - timedelta(hours=1)
        day_ago = now - timedelta(days=1)
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(tasks.c.process, tasks.c.status, func.count()).group_by(
                    tasks.c.process, tasks.c.status
                )
            ).all()
            last_hour: dict[str, int] = dict(
                conn.execute(
                    select(tasks.c.status, func.count())
                    .where(tasks.c.finished_at >= hour_ago)
                    .group_by(tasks.c.status)
                ).all()
            )
            durations = conn.execute(
                select(tasks.c.started_at, tasks.c.finished_at)
                .where(tasks.c.status == TaskStatus.DONE, tasks.c.finished_at >= day_ago)
                .limit(5000)
            ).all()

        by_status: dict[str, int] = {s.value: 0 for s in TaskStatus}
        by_process: dict[str, dict[str, int]] = {}
        for process, status, count in rows:
            by_status[status] += count
            by_process.setdefault(process, {})[status] = count

        seconds = [
            (_aware(f) - _aware(s)).total_seconds()  # type: ignore[operator]
            for s, f in durations
            if s is not None and f is not None
        ]
        return Summary(
            by_status=by_status,
            by_process=by_process,
            done_last_hour=last_hour.get(TaskStatus.DONE, 0),
            failed_last_hour=last_hour.get(TaskStatus.FAILED, 0),
            avg_duration_seconds=round(sum(seconds) / len(seconds), 2) if seconds else None,
        )

    # ---------- internos ----------
    def _transition(
        self,
        task_id: UUID,
        status: TaskStatus,
        attempt: int,
        event: str,
        detail: str | None,
        values: dict[str, Any],
    ) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                update(tasks)
                .where(tasks.c.id == task_id)
                .values(status=status, attempts=attempt, updated_at=self._clock(), **values)
            )
            self._event(conn, task_id, event, attempt, detail, None)

    def _event(
        self,
        conn: Connection,
        task_id: UUID,
        event: str,
        attempt: int,
        detail: str | None,
        worker_id: str | None,
    ) -> None:
        conn.execute(
            insert(task_events).values(
                task_id=task_id,
                event=event,
                attempt=attempt,
                detail=detail,
                worker_id=worker_id,
                at=self._clock(),
            )
        )

    @staticmethod
    def _record(row: Any, events: list[dict[str, Any]] | None = None) -> TaskRecord:
        return TaskRecord(
            id=row["id"],
            process=row["process"],
            status=TaskStatus(row["status"]),
            payload=row["payload"],
            output=row["output"],
            attempts=row["attempts"],
            last_error=row["last_error"],
            correlation_id=row["correlation_id"],
            worker_id=row["worker_id"],
            created_at=_aware(row["created_at"]),  # type: ignore[arg-type]
            updated_at=_aware(row["updated_at"]),  # type: ignore[arg-type]
            started_at=_aware(row["started_at"]),
            finished_at=_aware(row["finished_at"]),
            events=events or [],
        )


@dataclass(frozen=True, slots=True)
class Heartbeat:
    worker_id: str
    hostname: str
    platform: str
    processes: list[str]
    state: WorkerState
    current_task_id: UUID | None
    tasks_ok: int
    tasks_failed: int
    version: str
    started_at: datetime
    last_seen: datetime


class HeartbeatRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def beat(self, hb: Heartbeat) -> None:
        values = {
            "worker_id": hb.worker_id,
            "hostname": hb.hostname,
            "platform": hb.platform,
            "processes": hb.processes,
            "state": hb.state,
            "current_task_id": hb.current_task_id,
            "tasks_ok": hb.tasks_ok,
            "tasks_failed": hb.tasks_failed,
            "version": hb.version,
            "started_at": hb.started_at,
            "last_seen": hb.last_seen,
        }
        with self._engine.begin() as conn:
            stmt = _dialect_insert(conn)(bot_heartbeats).values(**values)
            stmt = stmt.on_conflict_do_update(
                index_elements=["worker_id"],
                set_={k: v for k, v in values.items() if k != "worker_id"},
            )
            conn.execute(stmt)

    def all(self) -> list[Heartbeat]:
        with self._engine.connect() as conn:
            rows = conn.execute(select(bot_heartbeats).order_by(bot_heartbeats.c.worker_id))
            return [
                Heartbeat(
                    worker_id=r.worker_id,
                    hostname=r.hostname,
                    platform=r.platform,
                    processes=list(r.processes),
                    state=WorkerState(r.state),
                    current_task_id=r.current_task_id,
                    tasks_ok=r.tasks_ok,
                    tasks_failed=r.tasks_failed,
                    version=r.version,
                    started_at=_aware(r.started_at),  # type: ignore[arg-type]
                    last_seen=_aware(r.last_seen),  # type: ignore[arg-type]
                )
                for r in rows
            ]
