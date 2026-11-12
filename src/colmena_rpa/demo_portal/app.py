from __future__ import annotations

import os
import random
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Annotated, Any

from fastapi import Cookie, FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from jinja2 import DictLoader, Environment, select_autoescape

MIN_COVERAGE = 0.6  # el acuerdo debe cubrir al menos el 60 % del saldo


@dataclass
class Client:
    documento: str
    nombre: str
    saldo: float
    dias_mora: int


SEED_CLIENTS = [
    Client("1012345678", "Laura Gómez Ríos", 2_450_000, 45),
    Client("1023456789", "Andrés Pérez Duarte", 980_000, 12),
    Client("1034567890", "María Fernanda Torres", 5_300_000, 95),
    Client("1045678901", "Julián Castro Medina", 1_750_000, 33),
    Client("1056789012", "Paola Rincón Vargas", 640_000, 61),
    Client("1067890123", "Camilo Herrera Ruiz", 3_100_000, 120),
    Client("1078901234", "Natalia Suárez León", 1_200_000, 8),
    Client("1089012345", "Sergio Morales Peña", 4_050_000, 75),
]

BASE = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Portal Cartera · {{ title }}</title>
<style>
body{font:15px system-ui,Segoe UI,sans-serif;margin:0;background:#eef2f5;color:#15202b}
header{background:#123047;color:#fff;padding:12px 24px;font-weight:600}
main{max-width:720px;margin:32px auto;background:#fff;padding:28px;border-radius:10px;
box-shadow:0 2px 10px #0001}
label{display:block;margin:12px 0 4px;font-weight:600}
input{padding:8px;width:100%;box-sizing:border-box;border:1px solid #c5d0da;border-radius:6px}
button,a.btn{margin-top:18px;background:#0d9488;color:#fff;border:0;padding:10px 16px;
border-radius:6px;cursor:pointer;text-decoration:none;display:inline-block}
.error-negocio,.error-sistema,.error-login{background:#fee2e2;color:#991b1b;padding:10px;
border-radius:6px}
.ok{background:#dcfce7;color:#166534;padding:12px;border-radius:6px}
dl{display:grid;grid-template-columns:160px 1fr;gap:6px}
</style></head><body><header>Portal de Gestión de Cartera (demo)</header>
<main>{% block content %}{% endblock %}</main></body></html>"""

TEMPLATES = {
    "base.html": BASE,
    "login.html": """{% extends "base.html" %}{% block content %}<h1>Iniciar sesión</h1>
{% if error %}<p class="error-login">{{ error }}</p>{% endif %}
<form method="post" action="/login"><label for="username">Usuario</label>
<input id="username" name="username" autocomplete="username">
<label for="password">Contraseña</label>
<input id="password" name="password" type="password" autocomplete="current-password">
<button id="submit" type="submit">Ingresar</button></form>{% endblock %}""",
    "clientes.html": """{% extends "base.html" %}{% block content %}<h1>Consulta de clientes</h1>
<form method="get" action="/clientes"><label for="documento">Documento</label>
<input id="documento" name="documento" value="{{ documento or '' }}">
<button id="buscar" type="submit">Buscar</button></form>
{% if documento and not client %}<p id="not-found" class="error-negocio">
No existe un cliente con documento {{ documento }}</p>{% endif %}
{% if client %}<h2 id="cliente-nombre">{{ client.nombre }}</h2><dl>
<dt>Documento</dt><dd>{{ client.documento }}</dd>
<dt>Saldo en mora</dt><dd id="saldo">{{ "{:,.0f}".format(client.saldo) }}</dd>
<dt>Días de mora</dt><dd>{{ client.dias_mora }}</dd></dl>
<a id="registrar-acuerdo" class="btn" href="/clientes/{{ client.documento }}/acuerdos/nuevo">
Registrar acuerdo de pago</a>{% endif %}{% endblock %}""",
    "acuerdo.html": """{% extends "base.html" %}{% block content %}
<h1>Acuerdo de pago · {{ client.nombre }}</h1>
<form method="post" action="/clientes/{{ client.documento }}/acuerdos">
<label for="cuotas">Número de cuotas</label><input id="cuotas" name="cuotas" type="number">
<label for="valor_cuota">Valor de la cuota</label><input id="valor_cuota" name="valor_cuota">
<label for="fecha_primer_pago">Fecha primer pago</label>
<input id="fecha_primer_pago" name="fecha_primer_pago" type="date">
<label for="referencia">Referencia externa</label><input id="referencia" name="referencia">
<button id="guardar" type="submit">Guardar acuerdo</button></form>{% endblock %}""",
    "resultado.html": """{% extends "base.html" %}{% block content %}
{% if confirmation %}<p class="ok">Acuerdo registrado. Confirmación:
<strong><span id="confirmation">{{ confirmation }}</span></strong></p>
{% elif business_error %}<p class="error-negocio">{{ business_error }}</p>
{% else %}<p class="error-sistema">{{ system_error }}</p>{% endif %}
<a class="btn" href="/clientes">Volver</a>{% endblock %}""",
}


def create_portal(
    username: str = "bot",
    password: str = "bot-demo",  # noqa: S107 - portal de demostración
    failure_rate: float = 0.0,
    clients: list[Client] | None = None,
    rand: random.Random | None = None,
    today: Callable[[], date] = date.today,
) -> FastAPI:
    env = Environment(loader=DictLoader(TEMPLATES), autoescape=select_autoescape())
    rng = rand or random.Random()
    directory = {c.documento: c for c in (clients or SEED_CLIENTS)}
    sessions: set[str] = set()
    agreements: dict[str, dict[str, Any]] = {}  # referencia -> acuerdo
    lock = threading.Lock()

    app = FastAPI(title="Portal de cartera (demo)", docs_url=None, redoc_url=None)

    def render(name: str, status: int = 200, **ctx: Any) -> HTMLResponse:
        return HTMLResponse(env.get_template(name).render(**ctx), status_code=status)

    def authenticated(token: str | None) -> bool:
        return token is not None and token in sessions

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/login", response_class=HTMLResponse)
    def login_form() -> HTMLResponse:
        return render("login.html", title="Iniciar sesión")

    @app.post("/login")
    def login(
        username_: Annotated[str, Form(alias="username")] = "",
        password_: Annotated[str, Form(alias="password")] = "",
    ) -> Response:
        if not (
            secrets.compare_digest(username_, username)
            and secrets.compare_digest(password_, password)
        ):
            return render(
                "login.html", status=401, title="Iniciar sesión", error="Credenciales inválidas"
            )
        token = secrets.token_urlsafe(24)
        sessions.add(token)
        response = RedirectResponse("/clientes", status_code=303)
        response.set_cookie("portal_session", token, httponly=True, samesite="lax")
        return response

    @app.get("/clientes", response_class=HTMLResponse)
    def clientes(
        documento: str | None = None,
        portal_session: Annotated[str | None, Cookie()] = None,
    ) -> Response:
        if not authenticated(portal_session):
            return RedirectResponse("/login", status_code=303)
        client = directory.get(documento or "")
        return render("clientes.html", title="Clientes", documento=documento, client=client)

    @app.get("/clientes/{documento}/acuerdos/nuevo", response_class=HTMLResponse)
    def nuevo_acuerdo(
        documento: str, portal_session: Annotated[str | None, Cookie()] = None
    ) -> Response:
        if not authenticated(portal_session):
            return RedirectResponse("/login", status_code=303)
        client = directory.get(documento)
        if client is None:
            return render("clientes.html", 404, title="Clientes", documento=documento, client=None)
        return render("acuerdo.html", title="Acuerdo", client=client)

    @app.post("/clientes/{documento}/acuerdos", response_class=HTMLResponse)
    def crear_acuerdo(
        documento: str,
        cuotas: Annotated[int, Form()],
        valor_cuota: Annotated[float, Form()],
        fecha_primer_pago: Annotated[date, Form()],
        referencia: Annotated[str, Form()] = "",
        portal_session: Annotated[str | None, Cookie()] = None,
    ) -> Response:
        if not authenticated(portal_session):
            return RedirectResponse("/login", status_code=303)
        if rng.random() < failure_rate:
            return render(
                "resultado.html",
                503,
                title="Error",
                system_error="Servicio temporalmente no disponible (503)",
            )
        client = directory.get(documento)
        if client is None:
            return render(
                "resultado.html",
                422,
                title="Error",
                business_error=f"Cliente {documento} no existe",
            )

        with lock:
            if referencia and referencia in agreements:
                existing = agreements[referencia]
                return render("resultado.html", title="Acuerdo", confirmation=existing["id"])

            total = cuotas * valor_cuota
            error = None
            if not 1 <= cuotas <= 36:
                error = "El número de cuotas debe estar entre 1 y 36"
            elif fecha_primer_pago < today():
                error = "La fecha del primer pago no puede estar en el pasado"
            elif total < client.saldo * MIN_COVERAGE:
                error = f"El acuerdo no cubre el {MIN_COVERAGE:.0%} mínimo del saldo en mora"
            elif total > client.saldo * 1.5:
                error = "El total del acuerdo supera el máximo permitido"
            if error:
                return render("resultado.html", 422, title="Error", business_error=error)

            agreement_id = f"AC-{len(agreements) + 100001}"
            agreements[referencia or agreement_id] = {
                "id": agreement_id,
                "documento": documento,
                "cuotas": cuotas,
                "valor_cuota": valor_cuota,
                "fecha_primer_pago": fecha_primer_pago.isoformat(),
            }
        return render("resultado.html", title="Acuerdo", confirmation=agreement_id)

    @app.get("/api/acuerdos")
    def list_agreements() -> list[dict[str, Any]]:
        return list(agreements.values())

    return app


def build() -> FastAPI:
    return create_portal(
        username=os.getenv("PORTAL_USER", "bot"),
        password=os.getenv("PORTAL_PASSWORD", "bot-demo"),
        failure_rate=float(os.getenv("PORTAL_FAILURE_RATE", "0.15")),
    )
