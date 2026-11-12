"""Punto de entrada: ``colmena-obrera``."""

from __future__ import annotations

from colmena_rpa.bots.catalog import build_registry
from colmena_rpa.config import get_settings
from colmena_rpa.logging import configure_logging, get_logger
from colmena_rpa.messaging.retry import RetryPolicy
from colmena_rpa.persistence import HeartbeatRepository, TaskRepository, create_db_engine
from colmena_rpa.worker.heartbeat import HeartbeatService
from colmena_rpa.worker.processor import TaskProcessor
from colmena_rpa.worker.runtime import Worker


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    log = get_logger("colmena_rpa.worker")

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
