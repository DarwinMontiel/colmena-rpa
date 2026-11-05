"""Contrato de un bot (patrón *template method*: setup → run* → teardown)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar
from uuid import UUID


@dataclass(frozen=True, slots=True)
class BotContext:
    task_id: UUID
    attempt: int
    worker_id: str
    correlation_id: str | None = None


@dataclass(frozen=True, slots=True)
class BotResult:
    output: dict[str, Any] = field(default_factory=dict)


class Bot(ABC):
    """Un bot vive lo mismo que el worker: ``setup`` abre recursos caros (navegador,
    sesiones) una sola vez y ``run`` procesa una tarea. Debe lanzar
    ``BusinessRuleError`` o ``TransientError`` para que el worker decida si reintenta."""

    name: ClassVar[str]

    def setup(self) -> None:  # noqa: B027 - gancho opcional
        """Inicializa recursos de larga vida."""

    @abstractmethod
    def run(self, ctx: BotContext, payload: dict[str, Any]) -> BotResult:
        """Procesa una tarea. Debe ser idempotente respecto a ``ctx.task_id``."""

    def teardown(self) -> None:  # noqa: B027 - gancho opcional
        """Libera recursos."""
