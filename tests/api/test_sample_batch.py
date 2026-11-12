"""El lote de ejemplo del README cumple lo que promete, se pruebe el día que se pruebe."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from colmena_rpa.demo_portal.app import create_portal
from colmena_rpa.producer.loader import read_tasks

SAMPLE = Path(__file__).parents[2] / "data" / "sample_tasks.csv"


def _run_batch(today: date) -> list[tuple[str, int, str]]:
    portal = TestClient(create_portal(username="bot", password="s", today=lambda: today))
    portal.post("/login", data={"username": "bot", "password": "s"})
    results = []
    for message in read_tasks(SAMPLE, "payment_agreement", "demo", today=today):
        p = message.payload
        response = portal.post(
            f"/clientes/{p['documento']}/acuerdos",
            data={
                "cuotas": str(p["cuotas"]),
                "valor_cuota": str(p["valor_cuota"]),
                "fecha_primer_pago": p["fecha_primer_pago"],
                "referencia": str(message.task_id),
            },
        )
        results.append((p["documento"], response.status_code, response.text))
    return results


@pytest.mark.parametrize("today", [date.today(), date(2030, 2, 28)])
def test_sample_batch_outcomes(today: date) -> None:
    results = _run_batch(today)

    ok = [doc for doc, status, _ in results if status == 200]
    rejected = {doc: html for doc, status, html in results if status == 422}

    assert len(ok) == 8
    assert set(rejected) == {"1099887766", "1012345678"}
    assert "no existe" in rejected["1099887766"]
    assert "no cubre" in rejected["1012345678"]
    assert all("pasado" not in html for _, _, html in results)
