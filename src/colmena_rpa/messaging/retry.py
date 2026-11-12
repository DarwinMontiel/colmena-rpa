"""Política de reintentos con backoff escalonado."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """``max_attempts`` incluye el primer intento.

    Con ``max_attempts=4`` y ``delays=(10, 60, 300)`` una tarea se ejecuta en t=0, +10s,
    +60s y +300s; si el cuarto intento falla se envía a la DLQ.
    """

    max_attempts: int
    delays_seconds: tuple[int, ...]

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts debe ser >= 1")
        if not self.delays_seconds:
            raise ValueError("se requiere al menos un delay")

    def should_retry(self, attempt: int) -> bool:
        return attempt < self.max_attempts

    def delay_for(self, attempt: int) -> int:
        """Delay a aplicar después de que falla el intento ``attempt`` (1-based)."""
        index = min(max(attempt, 1) - 1, len(self.delays_seconds) - 1)
        return self.delays_seconds[index]
