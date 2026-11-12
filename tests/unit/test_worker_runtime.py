"""Adaptador pika del worker probado sin RabbitMQ: canal y conexión falsos."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy.exc import OperationalError

from colmena_rpa.bots.registry import BotRegistry
from colmena_rpa.config import Settings
from colmena_rpa.domain.models import TaskMessage
from colmena_rpa.persistence import TaskRepository
from colmena_rpa.worker.processor import Outcome, OutcomeKind
from colmena_rpa.worker.runtime import Worker


class FakeChannel:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, dict[str, Any]]] = []

    def basic_ack(self, delivery_tag: int) -> None:
        self.calls.append(("ack", delivery_tag, {}))

    def basic_nack(self, delivery_tag: int, requeue: bool = True) -> None:
        self.calls.append(("nack", delivery_tag, {"requeue": requeue}))

    def basic_reject(self, delivery_tag: int, requeue: bool = True) -> None:
        self.calls.append(("reject", delivery_tag, {"requeue": requeue}))


class FakeConnection:
    """Ejecuta de inmediato lo que el worker programa en el hilo de la conexión."""

    def add_callback_threadsafe(self, callback: Callable[[], None]) -> None:
        callback()


class FakeHeartbeat:
    def __init__(self) -> None:
        self.events: list[tuple[str, Any]] = []

    def busy(self, task_id: Any) -> None:
        self.events.append(("busy", task_id))

    def idle(self, succeeded: bool | None) -> None:
        self.events.append(("idle", succeeded))


class CrashingProcessor:
    """Simula PostgreSQL caído: la excepción ocurre fuera del try del bot."""

    def handle(self, message: TaskMessage) -> Outcome:
        raise OperationalError("UPDATE tasks ...", {}, Exception("connection refused"))


class AckProcessor:
    def handle(self, message: TaskMessage) -> Outcome:
        return Outcome(OutcomeKind.ACK)


def _worker(settings: Settings, processor: Any, heartbeat: FakeHeartbeat) -> Worker:
    worker = Worker(settings, processor, BotRegistry(), heartbeat)  # type: ignore[arg-type]
    worker.crash_backoff_seconds = 0
    worker._connection = FakeConnection()
    return worker


def test_infrastructure_crash_nacks_message_and_frees_the_worker(settings: Settings) -> None:
    heartbeat = FakeHeartbeat()
    channel = FakeChannel()
    message = TaskMessage(process="scripted")
    worker = _worker(settings, CrashingProcessor(), heartbeat)

    worker._process(channel, 7, message.to_bytes())

    assert channel.calls == [("nack", 7, {"requeue": True})]
    assert heartbeat.events == [("busy", message.task_id), ("idle", None)]


def test_crash_through_executor_does_not_leave_message_unsettled(settings: Settings) -> None:
    """Reproduce el camino real: ``_on_message`` envía el trabajo al executor."""
    heartbeat = FakeHeartbeat()
    channel = FakeChannel()
    worker = _worker(settings, CrashingProcessor(), heartbeat)

    class Method:
        delivery_tag = 3

    worker._on_message(channel, Method(), None, TaskMessage(process="scripted").to_bytes())
    worker._executor.shutdown(wait=True)

    assert channel.calls == [("nack", 3, {"requeue": True})]


def test_invalid_message_is_rejected_without_requeue(settings: Settings) -> None:
    channel = FakeChannel()
    worker = _worker(settings, AckProcessor(), FakeHeartbeat())

    worker._process(channel, 1, b"{no es json")

    assert channel.calls == [("reject", 1, {"requeue": False})]


def test_successful_outcome_is_acked(settings: Settings) -> None:
    heartbeat = FakeHeartbeat()
    channel = FakeChannel()
    worker = _worker(settings, AckProcessor(), heartbeat)
    worker._publisher = object()  # type: ignore[assignment]

    worker._process(channel, 9, TaskMessage(process="scripted").to_bytes())

    assert channel.calls == [("ack", 9, {})]
    assert heartbeat.events[-1] == ("idle", True)


@pytest.mark.parametrize("failing", ["mark_running", "mark_done"])
def test_repository_failure_propagates_from_processor(
    make_processor: Any, repo: TaskRepository, message: TaskMessage, failing: str
) -> None:
    """El procesador no oculta fallas de la base de datos: las maneja el runtime."""
    from tests.conftest import ScriptedBot

    def boom(*_args: Any, **_kwargs: Any) -> None:
        raise OperationalError("SELECT 1", {}, Exception("db down"))

    setattr(repo, failing, boom)
    with pytest.raises(OperationalError):
        make_processor(ScriptedBot(["ok"])).handle(message)
