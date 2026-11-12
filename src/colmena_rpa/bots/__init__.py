"""Bots RPA. Cada bot implementa ``Bot`` y se registra en ``BotRegistry`` por nombre de proceso."""

from colmena_rpa.bots.base import Bot, BotContext, BotResult
from colmena_rpa.bots.registry import BotRegistry

__all__ = ["Bot", "BotContext", "BotRegistry", "BotResult"]
