"""Punto de entrada: ``rpa-worker``."""

from __future__ import annotations

from rpa_orchestrator.bots.catalog import build_registry
from rpa_orchestrator.config import get_settings
from rpa_orchestrator.logging import configure_logging, get_logger
from rpa_orchestrator.messaging.retry import RetryPolicy
from rpa_orchestrator.persistence import HeartbeatRepository, TaskRepository, create_db_engine
from rpa_orchestrator.worker.heartbeat import HeartbeatService
from rpa_orchestrator.worker.processor import TaskProcessor
from rpa_orchestrator.worker.runtime import Worker


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    log = get_logger("rpa_orchestrator.worker")

    engine = create_db_engine(settings.database_url)
    registry = build_registry(settings)
    unknown = set(settings.processes) - set(registry.processes)
    if unknown:
        raise SystemExit(f"Procesos sin bot registrado: {sorted(unknown)}")

    processor = TaskProcessor(
        repository=TaskRepository(engine),
        registry=registry,
        policy=RetryPolicy(settings.max_attempts, tuple(settings.retry_delays_seconds)),
        worker_id=settings.worker_id,
    )
    heartbeat = HeartbeatService(
        HeartbeatRepository(engine),
        settings.worker_id,
        settings.processes,
        settings.heartbeat_interval_seconds,
    )
    log.info("worker.starting", worker_id=settings.worker_id, processes=settings.processes)
    Worker(settings, processor, registry, heartbeat).run_forever()


if __name__ == "__main__":
    main()
