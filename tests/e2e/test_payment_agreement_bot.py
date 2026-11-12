"""Prueba de punta a punta: el bot real (Playwright + Chromium) opera el portal demo.

Requiere ``playwright install chromium``. Se ejecuta con ``pytest -m e2e``.
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import uvicorn

from colmena_rpa.bots.base import BotContext
from colmena_rpa.config import Settings
from colmena_rpa.demo_portal.app import create_portal
from colmena_rpa.domain.errors import BusinessRuleError

pytestmark = pytest.mark.e2e

FUTURE = (date.today() + timedelta(days=15)).isoformat()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def portal_url() -> Iterator[str]:
    port = _free_port()
    config = uvicorn.Config(create_portal(), host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(scope="module")
def bot(portal_url: str, tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    from colmena_rpa.bots.payment_agreement import PaymentAgreementBot

    settings = Settings(
        portal_url=portal_url,
        artifacts_dir=str(tmp_path_factory.mktemp("artifacts")),
        browser_timeout_ms=10_000,
    )
    instance = PaymentAgreementBot(settings)
    instance.setup()
    yield instance
    instance.teardown()


def _ctx() -> BotContext:
    return BotContext(task_id=uuid4(), attempt=1, worker_id="e2e")


def test_registers_agreement_and_is_idempotent(bot) -> None:  # type: ignore[no-untyped-def]
    ctx = _ctx()
    payload = {
        "documento": "1012345678",
        "cuotas": 6,
        "valor_cuota": 300000,
        "fecha_primer_pago": FUTURE,
    }

    first = bot.run(ctx, payload)
    again = bot.run(ctx, payload)  # misma tarea reprocesada

    assert first.output["confirmation"].startswith("AC-")
    assert again.output["confirmation"] == first.output["confirmation"]


def test_unknown_client_is_business_error_with_evidence(bot) -> None:  # type: ignore[no-untyped-def]
    ctx = _ctx()
    payload = {
        "documento": "1099887766",
        "cuotas": 2,
        "valor_cuota": 1000,
        "fecha_primer_pago": FUTURE,
    }
    with pytest.raises(BusinessRuleError, match="no existe"):
        bot.run(ctx, payload)
    assert list(Path(bot._artifacts).glob(f"{ctx.task_id}-*.png"))


def test_invalid_payload_is_business_error(bot) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(BusinessRuleError, match="payload inválido"):
        bot.run(_ctx(), {"documento": "abc", "cuotas": 0})
