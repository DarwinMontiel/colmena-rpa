"""Núcleo del worker, independiente de RabbitMQ: recibe un mensaje y decide su desenlace.

Separar la decisión (``Outcome``) de la acción sobre el broker (ack / retry / DLQ) permite
probar toda la lógica de negocio sin un RabbitMQ real.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from colmena_rpa.bots.base import BotContext
from colmena_rpa.bots.registry import BotRegistry
from colmena_rpa.domain.errors import BusinessRuleError
from colmena_rpa.domain.models import TaskMessage
from colmena_rpa.logging import get_logger
from colmena_rpa.messaging.retry import RetryPolicy
from colmena_rpa.persistence.repository import TaskRepository

log = get_logger(__name__)


class OutcomeKind(StrEnum):
    ACK = "ack"  # terminado (o duplicado): confirmar el mensaje
    RETRY = "retry"  # publicar en la cola de espera y confirmar
    DEAD = "dead"  # publicar en la DLQ y confirmar


@dataclass(frozen=True, slots=True)
class Outcome:
    kind: OutcomeKind
    delay_seconds: int | None = None
    error: str | None = None
    output: dict[str, Any] = field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return self.kind is OutcomeKind.ACK and self.error is None


def _describe(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:2000]


class TaskProcessor:
    def __init__(
        self,
        repository: TaskRepository,
        registry: BotRegistry,
        policy: RetryPolicy,
        worker_id: str,
    ) -> None:
        self._repo = repository
        self._registry = registry
        self._policy = policy
        self._worker_id = worker_id

    def handle(self, message: TaskMessage) -> Outcome:
        bound = log.bind(
            task_id=str(message.task_id), process=message.process, attempt=message.attempt
        )

        status = self._repo.get_status(message.task_id)
        if status is not None and status.is_final:
            bound.info("task.duplicate_skipped", status=status)
            return Outcome(OutcomeKind.ACK)

        self._repo.mark_running(message, self._worker_id)
        ctx = BotContext(
            task_id=message.task_id,
            attempt=message.attempt,
            worker_id=self._worker_id,
            correlation_id=message.correlation_id,
        )

        try:
            bot = self._registry.get(message.process)
            result = bot.run(ctx, message.payload)
        except BusinessRuleError as exc:
            error = _describe(exc)
            self._repo.mark_failed(message.task_id, message.attempt, error)
            bound.warning("task.business_error", error=error)
            return Outcome(OutcomeKind.DEAD, error=error)
        except Exception as exc:
            error = _describe(exc)
            # El recurso pudo quedar en mal estado (p. ej. navegador colgado): recrearlo.
            self._registry.reset(message.process)
            if self._policy.should_retry(message.attempt):
                delay = self._policy.delay_for(message.attempt)
                self._repo.mark_retrying(message.task_id, message.attempt, error, delay)
                bound.warning("task.retry_scheduled", error=error, delay_seconds=delay)
                return Outcome(OutcomeKind.RETRY, delay_seconds=delay, error=error)
            self._repo.mark_failed(message.task_id, message.attempt, error)
            bound.error("task.attempts_exhausted", error=error)
            return Outcome(OutcomeKind.DEAD, error=error)

        self._repo.mark_done(message.task_id, message.attempt, result.output)
        bound.info("task.completed")
        return Outcome(OutcomeKind.ACK, output=result.output)
