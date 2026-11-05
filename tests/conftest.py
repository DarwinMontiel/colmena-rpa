from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import Engine

from rpa_orchestrator.bots.base import Bot, BotContext, BotResult
from rpa_orchestrator.bots.registry import BotRegistry
from rpa_orchestrator.config import Settings
from rpa_orchestrator.domain.errors import BusinessRuleError, TransientError
from rpa_orchestrator.domain.models import TaskMessage
from rpa_orchestrator.messaging.retry import RetryPolicy
from rpa_orchestrator.persistence import HeartbeatRepository, TaskRepository, create_db_engine
from rpa_orchestrator.persistence.tables import metadata
from rpa_orchestrator.worker.processor import TaskProcessor


class ScriptedBot(Bot):
    """Bot de prueba: ejecuta una secuencia de comportamientos ('ok', 'transient', 'business')."""

    name = "scripted"

    def __init__(self, script: list[str]) -> None:
        self.script = list(script)
        self.calls: list[BotContext] = []
        self.setups = 0
        self.teardowns = 0

    def setup(self) -> None:
        self.setups += 1

    def teardown(self) -> None:
        self.teardowns += 1

    def run(self, ctx: BotContext, payload: dict[str, Any]) -> BotResult:
        self.calls.append(ctx)
        action = self.script.pop(0) if self.script else "ok"
        if action == "transient":
            raise TransientError("portal caído")
        if action == "business":
            raise BusinessRuleError("cliente inexistente")
        if action == "crash":
            raise RuntimeError("bug inesperado")
        return BotResult({"confirmation": "AC-1", "echo": payload})


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url="sqlite+pysqlite:///:memory:",
        processes=["scripted"],
        max_attempts=3,
        retry_delays_seconds=[5, 30],
        offline_after_seconds=60,
        log_json=False,
    )


@pytest.fixture
def engine(settings: Settings) -> Iterator[Engine]:
    eng = create_db_engine(settings.database_url)
    metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def repo(engine: Engine) -> TaskRepository:
    return TaskRepository(engine)


@pytest.fixture
def heartbeats(engine: Engine) -> HeartbeatRepository:
    return HeartbeatRepository(engine)


@pytest.fixture
def make_processor(repo: TaskRepository):  # type: ignore[no-untyped-def]
    def factory(bot: ScriptedBot) -> TaskProcessor:
        registry = BotRegistry()
        registry.register("scripted", lambda: bot)
        return TaskProcessor(repo, registry, RetryPolicy(3, (5, 30)), worker_id="test-worker")

    return factory


@pytest.fixture
def message() -> TaskMessage:
    return TaskMessage(process="scripted", payload={"documento": "1012345678"}, correlation_id="b1")
