from __future__ import annotations

import random
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from rpa_orchestrator.demo_portal.app import create_portal

FUTURE = (date.today() + timedelta(days=10)).isoformat()


@pytest.fixture
def portal() -> TestClient:
    client = TestClient(create_portal(username="bot", password="secret"))
    client.post("/login", data={"username": "bot", "password": "secret"})
    return client


def _agreement(client: TestClient, **overrides: str) -> str:
    data = {
        "cuotas": "6",
        "valor_cuota": "300000",
        "fecha_primer_pago": FUTURE,
        "referencia": "t-1",
    }
    data.update(overrides)
    return client.post("/clientes/1012345678/acuerdos", data=data).text


def test_requires_login() -> None:
    client = TestClient(create_portal())
    response = client.get("/clientes", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_rejects_bad_credentials() -> None:
    client = TestClient(create_portal(password="secret"))
    response = client.post("/login", data={"username": "bot", "password": "x"})
    assert response.status_code == 401
    assert "error-login" in response.text


def test_search_client(portal: TestClient) -> None:
    assert "Laura Gómez Ríos" in portal.get("/clientes", params={"documento": "1012345678"}).text
    assert 'id="not-found"' in portal.get("/clientes", params={"documento": "999"}).text


def test_agreement_is_idempotent_by_reference(portal: TestClient) -> None:
    first = _agreement(portal)
    second = _agreement(portal)

    assert 'id="confirmation">AC-100001<' in first
    assert 'id="confirmation">AC-100001<' in second
    assert len(portal.get("/api/acuerdos").json()) == 1


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"valor_cuota": "1000"}, "no cubre"),
        ({"cuotas": "48"}, "entre 1 y 36"),
        ({"fecha_primer_pago": "2020-01-01"}, "pasado"),
    ],
)
def test_business_rules(portal: TestClient, overrides: dict[str, str], message: str) -> None:
    html = _agreement(portal, **overrides)
    assert "error-negocio" in html
    assert message in html


def test_failure_injection_returns_system_error() -> None:
    client = TestClient(create_portal(password="s", failure_rate=1.0, rand=random.Random(1)))
    client.post("/login", data={"username": "bot", "password": "s"})
    response = client.post(
        "/clientes/1012345678/acuerdos",
        data={"cuotas": "6", "valor_cuota": "300000", "fecha_primer_pago": FUTURE},
    )
    assert response.status_code == 503
    assert "error-sistema" in response.text
