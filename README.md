<div align="center">

# RPA Orchestrator

**Plataforma para operar bots RPA a escala: tareas distribuidas por RabbitMQ, trazabilidad en
PostgreSQL y monitoreo centralizado de bots en servidores Windows y Linux.**

[![CI](https://github.com/DarwinMontiel/colmena-rpa/actions/workflows/ci.yml/badge.svg)](https://github.com/DarwinMontiel/colmena-rpa/actions/workflows/ci.yml)
[![Demo](https://img.shields.io/badge/demo-GitHub%20Pages-0d9488)](https://darwinmontiel.github.io/colmena-rpa/)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-3776AB?logo=python&logoColor=white)
![RabbitMQ](https://img.shields.io/badge/RabbitMQ-quorum%20%2B%20DLQ-FF6600?logo=rabbitmq&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)
![Playwright](https://img.shields.io/badge/Playwright-Chromium-2EAD33?logo=playwright&logoColor=white)
[![mypy strict](https://img.shields.io/badge/mypy-strict-1f5082)](https://mypy-lang.org/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

[**Ver demo en vivo**](https://darwinmontiel.github.io/colmena-rpa/) ·
[Arquitectura](docs/architecture.md) ·
[Decisiones (ADR)](docs/adr/) ·
[Runbook](docs/runbook.md) ·
[Despliegue](docs/deployment.md)

<img src="docs/images/dashboard.png" alt="Dashboard del monitor con KPIs, workers y tareas" width="900">

</div>

> **English summary** — Production-style RPA platform in Python. Producers publish tasks to
> RabbitMQ; horizontally-scalable workers run Playwright bots against web applications, with
> tiered retry queues (TTL + dead-lettering), a DLQ, business vs. system error classification and
> three layers of idempotency. Every state change is audited in PostgreSQL, workers report
> heartbeats, and a FastAPI monitor exposes a dashboard, a REST API and Prometheus metrics.
> Ships with Docker Compose, systemd units, Windows Server services (NSSM), Alembic migrations
> and a CI pipeline with unit, API, E2E (real browser) and integration (real RabbitMQ +
> PostgreSQL) tests.

---

## El problema

En una operación de **gestión de cartera** hay procesos repetitivos sobre aplicativos web sin API:
registrar acuerdos de pago, actualizar gestiones, descargar soportes. Un bot aislado los
automatiza, pero en producción aparecen las preguntas difíciles:

- ¿Cómo reparto miles de casos entre varios bots y servidores?
- ¿Qué pasa cuando el aplicativo se cae a mitad del lote? ¿Y si un servidor se reinicia?
- ¿Cómo evito registrar dos veces el mismo acuerdo?
- ¿Cómo sabe operación qué bots están vivos y qué casos fallaron y por qué?

Este proyecto responde esas preguntas con una arquitectura orientada a mensajes.

## Qué incluye

| | |
|---|---|
| **Distribución de carga** | Cola por proceso en RabbitMQ (quorum), `prefetch=1`, *competing consumers*. Escalar = agregar workers. |
| **Reintentos inteligentes** | Colas de espera con TTL (10 s → 60 s → 300 s) que devuelven el mensaje al vencer. Sin `sleep`, sin plugins. |
| **Errores de negocio vs. sistema** | Como *Business/System Exceptions* de Blue Prism: los de negocio van directo a la DLQ con el motivo; los de sistema se reintentan. |
| **Idempotencia en 3 capas** | `task_id` determinístico al cargar, verificación de estado final en el worker y referencia idempotente en el aplicativo. |
| **Trazabilidad completa** | Cada transición queda en `task_events` (quién, cuándo, intento, detalle) + captura de pantalla como evidencia ante fallas. |
| **Monitoreo de bots** | Latidos por worker (host, SO, estado, tarea actual, contadores), salud `ONLINE/OFFLINE`, dashboard y `/metrics` para Prometheus. |
| **Operación real** | Parada ordenada (SIGTERM/SIGINT/SIGBREAK), reconexión con backoff, systemd en Linux, servicios NSSM en Windows Server, runbook. |
| **Calidad** | `mypy --strict`, Ruff (incluye reglas de seguridad), 55+ pruebas: unitarias, API, E2E con navegador real e integración con RabbitMQ y PostgreSQL. |

## Arquitectura

```mermaid
flowchart LR
    CSV[(Lote CSV)] --> P[colmena-carga]
    P -- registra PENDING --> DB[(PostgreSQL)]
    P -- publica --> EX{{rpa.tasks}}
    EX --> Q[[rpa.payment_agreement]]
    Q --> W1[worker Linux]
    Q --> W2[worker Windows]
    W1 & W2 -- Playwright --> PORTAL[Aplicativo web]
    W1 & W2 -- falla transitoria --> RQ[[retry 10s / 60s / 300s]]
    RQ -- TTL vencido --> EX
    W1 & W2 -- error de negocio --> DLQ[[DLQ]]
    W1 & W2 -- estado, eventos, latidos --> DB
    M[colmena-monitor · FastAPI] --> DB
    M -- reprocesar --> EX
    OPS((Operación)) --> M
    PROM[Prometheus] -- /metrics --> M
```

El núcleo del worker (`TaskProcessor`) **no conoce RabbitMQ**: recibe un mensaje y devuelve un
desenlace (`ACK`, `RETRY` o `DEAD`). El adaptador de pika lo traduce a operaciones del broker. Así
toda la lógica de reintentos e idempotencia se prueba en milisegundos sin infraestructura.
Detalle completo en [docs/architecture.md](docs/architecture.md).

```mermaid
stateDiagram-v2
    direction LR
    [*] --> PENDING
    PENDING --> RUNNING
    RUNNING --> DONE
    RUNNING --> RETRYING: error de sistema
    RETRYING --> RUNNING: vence TTL
    RUNNING --> FAILED: error de negocio / sin intentos
    FAILED --> PENDING: reproceso
```

## Inicio rápido

### Con Docker (plataforma completa)

```bash
git clone https://github.com/DarwinMontiel/colmena-rpa.git
cd colmena-rpa
docker compose up --build -d                       # postgres, rabbitmq, migraciones, portal, 2 workers, monitor
docker compose run --rm carga colmena-carga encolar --archivo data/sample_tasks.csv
```

- Monitor: <http://localhost:8000> · API: <http://localhost:8000/docs>
- RabbitMQ: <http://localhost:15672> (guest/guest) — mira las colas de retry y la DLQ en acción
- Portal demo: <http://localhost:8001> — falla con 503 el 15 % de las veces para ejercitar reintentos

El lote de ejemplo incluye casos que terminan bien, uno con cliente inexistente y otro que no
cumple la regla de cobertura mínima: verás ambos en **Fallidas** con su motivo y evidencia.

### Desarrollo local

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
make install        # dependencias + Chromium + pre-commit
make infra          # solo PostgreSQL y RabbitMQ en Docker
make migrate
colmena-obrera          # en otra terminal: colmena-monitor
```

## Pruebas

| Suite | Comando | Qué valida |
|---|---|---|
| Unitarias + API | `make test` | Política de reintentos, topología, publicación, procesador, repositorios, latidos, endpoints, métricas, migraciones vs. modelo |
| E2E | `make e2e` | El bot real con Chromium inicia sesión, busca el cliente, registra el acuerdo, es idempotente y guarda evidencia |
| Integración | `make integration` | Worker real contra RabbitMQ y PostgreSQL: éxito, reintento por TTL y DLQ de punta a punta |

Las tres suites corren en [GitHub Actions](.github/workflows/ci.yml) en cada push, junto con
Ruff, mypy y el build de la imagen Docker.

## Configuración

Todo se configura por variables de entorno con prefijo `RPA_` (ver [.env.example](.env.example)):

| Variable | Por defecto | Descripción |
|---|---|---|
| `RPA_DATABASE_URL` | `postgresql+psycopg://rpa:rpa@localhost:5432/rpa` | Conexión a PostgreSQL |
| `RPA_AMQP_URL` | `amqp://guest:guest@localhost:5672/%2F` | Conexión a RabbitMQ |
| `RPA_PROCESSES` | `["payment_agreement"]` | Procesos (colas) que consume este worker |
| `RPA_MAX_ATTEMPTS` | `4` | Intentos totales antes de la DLQ |
| `RPA_RETRY_DELAYS_SECONDS` | `[10,60,300]` | Espera entre intentos |
| `RPA_HEARTBEAT_INTERVAL_SECONDS` | `15` | Frecuencia del latido |
| `RPA_OFFLINE_AFTER_SECONDS` | `60` | Umbral para marcar un worker `OFFLINE` |
| `RPA_PORTAL_URL` / `_USER` / `_PASSWORD` | demo | Aplicativo que opera el bot |

## Estructura

```
src/colmena_rpa/
├── domain/          # modelos y errores (sin dependencias de infraestructura)
├── messaging/       # topología RabbitMQ, publicación con confirms, política de reintentos
├── persistence/     # SQLAlchemy Core, repositorios, esquema
├── bots/            # contrato Bot, registro y bot de acuerdos de pago (Playwright)
├── worker/          # procesador (núcleo), runtime pika, latidos
├── producer/        # CLI de carga de lotes
├── monitor/         # API FastAPI, métricas Prometheus y dashboard (HTML/CSS/JS)
└── demo_portal/     # aplicativo web simulado para demos y pruebas E2E
alembic/             # migraciones
deploy/              # systemd (Linux) y NSSM (Windows Server)
docs/                # arquitectura, ADRs, runbook, despliegue
tests/               # unit · api · e2e · integration
```

## Decisiones de diseño

| ADR | Decisión |
|---|---|
| [0001](docs/adr/0001-rabbitmq-como-broker.md) | RabbitMQ (y no una tabla-cola, Redis o Kafka) como broker |
| [0002](docs/adr/0002-reintentos-con-colas-ttl.md) | Reintentos con colas de TTL fijo para evitar *head-of-line blocking* |
| [0003](docs/adr/0003-idempotencia-y-at-least-once.md) | *At-least-once* + idempotencia en tres capas |
| [0004](docs/adr/0004-clasificacion-de-errores-rpa.md) | Errores de negocio vs. sistema, al estilo Blue Prism |
| [0005](docs/adr/0005-monitoreo-por-heartbeats.md) | Monitoreo por latidos en PostgreSQL |

## Hoja de ruta

- [ ] Autenticación del monitor con OIDC (Azure AD / Keycloak).
- [ ] Programación de lotes (cron) desde el monitor.
- [ ] Panel de Grafana versionado como código.
- [ ] Bot de descarga de soportes con validación de archivos.

## Autor

**Darwin Montiel Mora** — Desarrollador RPA & Backend · Ingeniero de Sistemas
[LinkedIn](https://www.linkedin.com/in/darwin-montiel-mora-925216206) · [GitHub](https://github.com/DarwinMontiel)

Licencia [MIT](LICENSE).
