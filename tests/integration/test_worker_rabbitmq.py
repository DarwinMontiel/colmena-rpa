"""Integración con RabbitMQ y PostgreSQL reales (``docker compose up -d rabbitmq postgres``).

Se ejecuta en CI con *service containers*: ``pytest -m integration``.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable, Iterator
from uuid import uuid4

import pika
import pytest
from sqlalchemy import Engine, text

from colmena_rpa.bots.registry import BotRegistry
from colmena_rpa.config import Settings
from colmena_rpa.domain.models import TaskMessage, TaskStatus
from colmena_rpa.messaging.publisher import open_publisher
from colmena_rpa.messaging.retry import RetryPolicy
from colmena_rpa.messaging.topology import ProcessTopology
from colmena_rpa.persistence import HeartbeatRepository, TaskRepository, create_db_engine
from colmena_rpa.persistence.tables import metadata
from colmena_rpa.worker.heartbeat import HeartbeatService
from colmena_rpa.worker.processor import TaskProcessor
from colmena_rpa.worker.runtime import Worker
from tests.conftest import ScriptedBot

pytestmark = pytest.mark.integration


@pytest.fixture
def it_settings() -> Settings:
    suffix = uuid4().hex[:8]
    return Settings(
        database_url=os.getenv(
            "RPA_DATABASE_URL", "postgresql+psycopg://rpa:rpa@localhost:5432/rpa"
        ),
        amqp_url=os.getenv("RPA_AMQP_URL", "amqp://guest:guest@localhost:5672/%2F"),
        exchange=f"it.{suffix}",
        processes=[f"scripted_{suffix}"],
        max_attempts=2,
        retry_delays_seconds=[1],
        heartbeat_interval_seconds=1,
        worker_id=f"it-{suffix}",
        log_json=False,
    )


@pytest.fixture
def pg(it_settings: Settings) -> Iterator[Engine]:
    engine = create_db_engine(it_settings.database_url)
    metadata.create_all(engine)
    yield engine
    engine.dispose()


def _wait_for(predicate: Callable[[], bool], timeout: float = 20) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.2)
    raise AssertionError("condición no alcanzada a tiempo")


def _start_worker(settings: Settings, engine: Engine, bot: ScriptedBot) -> Worker:
    registry = BotRegistry()
    registry.register(settings.processes[0], lambda: bot)
    processor = TaskProcessor(
        TaskRepository(engine),
        registry,
        RetryPolicy(settings.max_attempts, tuple(settings.retry_delays_seconds)),
        settings.worker_id,
    )
    heartbeat = HeartbeatService(
        HeartbeatRepository(engine), settings.worker_id, settings.processes, 1
    )
    worker = Worker(settings, processor, registry, heartbeat)
    worker._install_signal_handlers = lambda: None  # type: ignore[method-assign]
    threading.Thread(target=worker.run_forever, daemon=True).start()
    return worker


def test_end_to_end_success_retry_and_dead_letter(it_settings: Settings, pg: Engine) -> None:
    process = it_settings.processes[0]
    repo = TaskRepository(pg)
    # 1ª tarea: ok. 2ª: falla transitoria y luego ok. 3ª: error de negocio -> DLQ.
    bot = ScriptedBot(["ok", "transient", "ok", "business"])
    ok, flaky, bad = (TaskMessage(process=process, payload={"n": i}) for i in range(3))

    worker = _start_worker(it_settings, pg, bot)
    try:
        delays = tuple(it_settings.retry_delays_seconds)
        with open_publisher(it_settings.amqp_url, it_settings.exchange, delays) as publisher:
            for msg in (ok, flaky):
                repo.register_pending(msg)
                publisher.publish(msg)
            _wait_for(lambda: repo.get_status(flaky.task_id) is TaskStatus.DONE)
            repo.register_pending(bad)
            publisher.publish(bad)
            _wait_for(lambda: repo.get_status(bad.task_id) is TaskStatus.FAILED)

        assert repo.get_status(ok.task_id) is TaskStatus.DONE
        flaky_record = repo.get(flaky.task_id)
        assert flaky_record is not None
        assert flaky_record.attempts == 2
        assert "RETRY_SCHEDULED" in [e["event"] for e in flaky_record.events]

        topology = ProcessTopology(it_settings.exchange, process, delays)
        connection = pika.BlockingConnection(pika.URLParameters(it_settings.amqp_url))
        channel = connection.channel()
        _wait_for(
            lambda: (
                channel.queue_declare(topology.dead_letter_queue, passive=True).method.message_count
                == 1
            )
        )
        connection.close()

        with pg.connect() as conn:
            seen = conn.execute(
                text("SELECT tasks_ok, tasks_failed FROM bot_heartbeats WHERE worker_id = :w"),
                {"w": it_settings.worker_id},
            ).one()
        assert tuple(seen) == (2, 1)
    finally:
        worker.stop()
