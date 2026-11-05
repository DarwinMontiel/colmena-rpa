"""API de monitoreo centralizado de bots (FastAPI)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from datetime import datetime
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, generate_latest
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector
from sqlalchemy import Engine, text

from rpa_orchestrator import __version__
from rpa_orchestrator.config import Settings
from rpa_orchestrator.domain.models import TaskMessage, TaskStatus, utcnow
from rpa_orchestrator.messaging.publisher import Publisher, open_publisher
from rpa_orchestrator.monitor.schemas import (
    BotOut,
    EventOut,
    RequeueOut,
    SummaryOut,
    TaskDetailOut,
    TaskOut,
)
from rpa_orchestrator.persistence import HeartbeatRepository, TaskRepository
from rpa_orchestrator.persistence.repository import Heartbeat, TaskRecord

STATIC_DIR = Path(__file__).parent / "static"

PublisherFactory = Callable[[], AbstractContextManager[Publisher]]


def _bot_out(hb: Heartbeat, now: datetime, offline_after: int) -> BotOut:
    elapsed = (now - hb.last_seen).total_seconds()
    return BotOut(
        worker_id=hb.worker_id,
        hostname=hb.hostname,
        platform=hb.platform,
        processes=hb.processes,
        state=hb.state,
        health="ONLINE" if elapsed <= offline_after else "OFFLINE",
        current_task_id=hb.current_task_id,
        tasks_ok=hb.tasks_ok,
        tasks_failed=hb.tasks_failed,
        version=hb.version,
        started_at=hb.started_at,
        last_seen=hb.last_seen,
        seconds_since_seen=round(elapsed, 1),
    )


def _task_out(record: TaskRecord) -> TaskOut:
    return TaskOut(
        id=record.id,
        process=record.process,
        status=record.status,
        attempts=record.attempts,
        last_error=record.last_error,
        correlation_id=record.correlation_id,
        worker_id=record.worker_id,
        created_at=record.created_at,
        updated_at=record.updated_at,
        started_at=record.started_at,
        finished_at=record.finished_at,
        duration_seconds=record.duration_seconds,
    )


class _MonitorCollector(Collector):
    """Expone métricas calculadas en cada *scrape* (sin estado en memoria)."""

    def __init__(self, tasks: TaskRepository, bots: Callable[[], list[BotOut]]) -> None:
        self._tasks = tasks
        self._bots = bots

    def collect(self) -> Iterator[GaugeMetricFamily]:
        summary = self._tasks.summary()
        by_status = GaugeMetricFamily(
            "rpa_tasks", "Tareas por proceso y estado", labels=["process", "status"]
        )
        for process, statuses in summary.by_process.items():
            for status, count in statuses.items():
                by_status.add_metric([process, status], count)
        yield by_status

        bots = self._bots()
        online = GaugeMetricFamily("rpa_bot_up", "1 si el worker reporta latido", labels=["worker"])
        for bot in bots:
            online.add_metric([bot.worker_id], 1 if bot.health == "ONLINE" else 0)
        yield online

        if summary.avg_duration_seconds is not None:
            yield GaugeMetricFamily(
                "rpa_task_duration_avg_seconds",
                "Duración promedio de tareas exitosas (24 h)",
                value=summary.avg_duration_seconds,
            )


def create_app(
    settings: Settings,
    engine: Engine,
    publisher_factory: PublisherFactory | None = None,
) -> FastAPI:
    tasks = TaskRepository(engine)
    heartbeats = HeartbeatRepository(engine)
    delays = tuple(settings.retry_delays_seconds)
    make_publisher: PublisherFactory = publisher_factory or (
        lambda: open_publisher(settings.amqp_url, settings.exchange, delays)
    )

    app = FastAPI(
        title="RPA Orchestrator · Monitor",
        version=__version__,
        description="Estado de bots, tareas y trazabilidad de ejecuciones.",
    )

    def list_bots() -> list[BotOut]:
        now = utcnow()
        return [_bot_out(hb, now, settings.offline_after_seconds) for hb in heartbeats.all()]

    registry = CollectorRegistry()
    registry.register(_MonitorCollector(tasks, list_bots))

    @app.get("/health", tags=["ops"])
    def health() -> dict[str, str]:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "version": __version__}

    @app.get("/metrics", tags=["ops"], include_in_schema=False)
    def metrics() -> Response:
        return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)

    @app.get("/api/summary", response_model=SummaryOut, tags=["monitor"])
    def summary() -> SummaryOut:
        data = tasks.summary()
        bots = list_bots()
        online = sum(1 for b in bots if b.health == "ONLINE")
        return SummaryOut(
            by_status=data.by_status,
            by_process=data.by_process,
            success_rate=data.success_rate,
            done_last_hour=data.done_last_hour,
            failed_last_hour=data.failed_last_hour,
            avg_duration_seconds=data.avg_duration_seconds,
            bots_online=online,
            bots_offline=len(bots) - online,
            generated_at=utcnow(),
        )

    @app.get("/api/bots", response_model=list[BotOut], tags=["monitor"])
    def bots() -> list[BotOut]:
        return list_bots()

    @app.get("/api/tasks", response_model=list[TaskOut], tags=["tasks"])
    def list_tasks(
        status: TaskStatus | None = None,
        process: str | None = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> list[TaskOut]:
        return [_task_out(r) for r in tasks.search(status, process, limit, offset)]

    @app.get("/api/tasks/{task_id}", response_model=TaskDetailOut, tags=["tasks"])
    def get_task(task_id: UUID) -> TaskDetailOut:
        record = tasks.get(task_id)
        if record is None:
            raise HTTPException(404, "tarea no encontrada")
        return TaskDetailOut(
            **_task_out(record).model_dump(),
            payload=record.payload,
            output=record.output,
            events=[EventOut(**e) for e in record.events],
        )

    @app.post("/api/tasks/{task_id}/requeue", response_model=RequeueOut, tags=["tasks"])
    def requeue(task_id: UUID) -> RequeueOut:
        message: TaskMessage | None = tasks.requeue(task_id)
        if message is None:
            raise HTTPException(409, "solo se pueden reprocesar tareas FAILED o PENDING")
        try:
            with make_publisher() as publisher:
                publisher.publish(message)
        except Exception as exc:
            tasks.mark_failed(task_id, 0, f"no se pudo republicar: {exc}")
            raise HTTPException(503, "broker no disponible") from exc
        return RequeueOut(task_id=task_id, status=TaskStatus.PENDING)

    @app.get("/", include_in_schema=False)
    def dashboard() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
