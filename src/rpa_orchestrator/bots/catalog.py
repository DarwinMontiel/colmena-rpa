"""Catálogo de bots disponibles. Agregar un proceso nuevo = una clase + una línea aquí."""

from __future__ import annotations

from rpa_orchestrator.bots.registry import BotRegistry
from rpa_orchestrator.config import Settings


def build_registry(settings: Settings) -> BotRegistry:
    # Importación diferida: el monitor y el productor no necesitan Playwright.
    from rpa_orchestrator.bots.payment_agreement import PaymentAgreementBot

    registry = BotRegistry()
    registry.register(PaymentAgreementBot.name, lambda: PaymentAgreementBot(settings))
    return registry
