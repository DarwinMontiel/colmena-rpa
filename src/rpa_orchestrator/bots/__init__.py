"""Bots RPA. Cada bot implementa ``Bot`` y se registra en ``BotRegistry`` por nombre de proceso."""

from rpa_orchestrator.bots.base import Bot, BotContext, BotResult
from rpa_orchestrator.bots.registry import BotRegistry

__all__ = ["Bot", "BotContext", "BotRegistry", "BotResult"]
