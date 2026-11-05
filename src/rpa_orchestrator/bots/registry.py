from __future__ import annotations

import contextlib
from collections.abc import Callable

from rpa_orchestrator.bots.base import Bot
from rpa_orchestrator.domain.errors import UnknownProcessError

BotFactory = Callable[[], Bot]


class BotRegistry:
    """Crea los bots de forma perezosa y los reutiliza (un navegador por worker, no por tarea)."""

    def __init__(self) -> None:
        self._factories: dict[str, BotFactory] = {}
        self._instances: dict[str, Bot] = {}

    def register(self, process: str, factory: BotFactory) -> None:
        if process in self._factories:
            raise ValueError(f"el proceso '{process}' ya está registrado")
        self._factories[process] = factory

    @property
    def processes(self) -> list[str]:
        return sorted(self._factories)

    def get(self, process: str) -> Bot:
        bot = self._instances.get(process)
        if bot is not None:
            return bot
        factory = self._factories.get(process)
        if factory is None:
            raise UnknownProcessError(f"proceso no registrado en este worker: {process}")
        bot = factory()
        bot.setup()
        self._instances[process] = bot
        return bot

    def reset(self, process: str) -> None:
        """Descarta la instancia (p. ej. tras un error de sistema) para recrearla limpia."""
        bot = self._instances.pop(process, None)
        if bot is not None:
            with contextlib.suppress(Exception):
                bot.teardown()

    def close_all(self) -> None:
        for process in list(self._instances):
            self.reset(process)
