<div align="center">

# Colmena RPA

**Bots obreros que registran acuerdos de pago de cartera sin perder casos ni duplicarlos:
tareas repartidas por RabbitMQ, reintentos con espera, trazabilidad en PostgreSQL y un panel
de operación para servidores Windows y Linux.**

[![CI](https://github.com/DarwinMontiel/colmena-rpa/actions/workflows/ci.yml/badge.svg)](https://github.com/DarwinMontiel/colmena-rpa/actions/workflows/ci.yml)
[![Demo](https://img.shields.io/badge/demo-GitHub%20Pages-0d9488)](https://darwinmontiel.github.io/colmena-rpa/)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-3776AB?logo=python&logoColor=white)
![RabbitMQ](https://img.shields.io/badge/RabbitMQ-quorum%20%2B%20DLQ-FF6600?logo=rabbitmq&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)
![Playwright](https://img.shields.io/badge/Playwright-Chromium-2EAD33?logo=playwright&logoColor=white)
[![mypy strict](https://img.shields.io/badge/mypy-strict-1f5082)](https://mypy-lang.org/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Licencia: MIT](https://img.shields.io/badge/licencia-MIT-green)](LICENSE)

[**Ver demo en vivo**](https://darwinmontiel.github.io/colmena-rpa/) ·
[Arquitectura](docs/architecture.md) ·
[Decisiones (ADR)](docs/adr/) ·
[Runbook](docs/runbook.md) ·
[Despliegue](docs/deployment.md)

<img src="docs/images/dashboard.png" alt="Panel de operación de Colmena RPA con indicadores, obreras y tareas" width="900">

</div>

---

## El problema

En una operación de **gestión de cartera** hay procesos repetitivos sobre aplicativos web sin API:
registrar acuerdos de pago, actualizar gestiones, descargar soportes. Un bot aislado los
automatiza, pero en producción aparecen las preguntas difíciles:

- ¿Cómo reparto miles de casos entre varios bots y servidores?
- ¿Qué pasa cuando el aplicativo se cae a mitad del lote? ¿Y si un servidor se reinicia?
- ¿Cómo evito registrar dos veces el mismo acuerdo?
- ¿Cómo sabe operación qué bots están vivos y qué casos fallaron y por qué?

**¿Por qué «Colmena»?** Porque así trabaja: muchas *obreras* (bots) idénticas toman trabajo de
una misma cola, ninguna es indispensable y la colmena sigue produciendo aunque una caiga.

## Un lunes de cobranza

Así se ve el lote de la demo. Son las 7:00 a. m. y llega `data/sample_tasks.csv` con diez
acuerdos de pago negociados el fin de semana. Los clientes son **ficticios** y viven en el portal
de cartera simulado que trae el repositorio.

| Cliente (ficticio) | Saldo en mora | Acuerdo cargado | Desenlace | Por qué |
|---|---|---|---|---|
| Laura Gómez Ríos · 45 días | $ 2.450.000 | 6 × $ 300.000 | ✅ Registrado | Cubre el 73 % del saldo |
| Andrés Pérez Duarte · 12 días | $ 980.000 | 3 × $ 220.000 | ✅ Registrado | 67 % del saldo |
| María Fernanda Torres · 95 días | $ 5.300.000 | 12 × $ 320.000 | ✅ Registrado | 72 % del saldo |
| Julián Castro Medina · 33 días | $ 1.750.000 | 4 × $ 300.000 | ✅ Registrado | 69 % del saldo |
| Paola Rincón Vargas · 61 días | $ 640.000 | 2 × $ 200.000 | ✅ Registrado | 63 % del saldo |
| Camilo Herrera Ruiz · 120 días | $ 3.100.000 | 10 × $ 250.000 | ✅ Registrado | 81 % del saldo |
| Natalia Suárez León · 8 días | $ 1.200.000 | 1 × $ 900.000 | ✅ Registrado | Pago único, 75 % del saldo |
| Sergio Morales Peña · 75 días | $ 4.050.000 | 8 × $ 400.000 | ✅ Registrado | 79 % del saldo |
| Documento 1099887766 | — | 6 × $ 150.000 | ⛔ Fallida | El cliente no existe: **error de negocio**, va a la DLQ sin reintentos |
| Laura Gómez Ríos (segunda fila) | $ 2.450.000 | 2 × $ 100.000 | ⛔ Fallida | Cubre el 8 % y la regla exige el 60 %: **error de negocio** |

Mientras tanto, el portal responde **503** en el 15 % de los intentos (falla inyectada a
propósito). Esas tareas pasan a **Reintentando**, esperan 10 s, 60 s o 300 s en una cola con TTL
y vuelven solas: ningún caso se pierde. Las dos fallidas quedan en el panel con su motivo y una
captura de pantalla como evidencia, listas para que cartera corrija el dato de origen.

Las fechas del CSV son **relativas** (`+7d`, `+15d`) y se resuelven el día de la carga, así que
el lote funciona igual hoy que dentro de un año. Una prueba automática recorre el lote contra el
portal en dos fechas distintas y exige exactamente 8 acuerdos registrados y 2 rechazos de negocio.

### La vida de un acuerdo de pago

```mermaid
sequenceDiagram
    autonumber
    participant C as colmena-carga
    participant DB as PostgreSQL
    participant Q as RabbitMQ
    participant O as Obrera (bot)
    participant P as Portal de cartera
    C->>DB: registra la tarea PENDING (task_id = UUID v5 de la fila)
    C->>Q: publica en rpa.payment_agreement
    Q->>O: entrega (prefetch = 1)
    O->>DB: reclama la tarea: PENDING → RUNNING (UPDATE condicional)
    O->>P: inicia sesión, busca el documento, diligencia el acuerdo
    P-->>O: 503 Servicio no disponible
    O->>DB: RETRYING + evento «reintento en 10 s»
    O->>Q: publica en la cola de espera de 10 s y confirma (ack)
    Note over Q: vence el TTL y el mensaje vuelve a la cola principal
    Q->>O: segunda entrega (intento 2)
    O->>P: misma referencia = task_id (idempotente)
    P-->>O: Confirmación AC-100001
    O->>DB: DONE + resultado + evento COMPLETED
    O->>Q: ack
```

## Qué incluye

| | |
|---|---|
| **Distribución de carga** | Cola por proceso en RabbitMQ (quorum), `prefetch=1`, *competing consumers*. Escalar = agregar obreras. |
| **Reintentos con espera** | Colas de espera con TTL (10 s → 60 s → 300 s) que devuelven el mensaje al vencer. Sin `sleep`, sin plugins. |
| **Errores de negocio vs. técnicos** | Como las *Business/System Exceptions* de Blue Prism: los de negocio van directo a la DLQ con el motivo; los técnicos se reintentan. |
| **Idempotencia en 3 capas** | `task_id` UUID v5 al cargar, reclamo atómico de la tarea en la obrera y referencia idempotente en el aplicativo. |
| **Trazabilidad completa** | Cada transición queda en `task_events` (quién, cuándo, intento, detalle) + captura de pantalla como evidencia ante fallas. |
| **Monitoreo de bots** | Latidos por obrera (host, SO, estado, tarea actual, contadores), panel en español y `/metrics` para Prometheus. |
| **Operación real** | Parada ordenada (SIGTERM/SIGINT/SIGBREAK), reconexión con backoff, `nack` con reencolado si cae la base de datos, systemd en Linux, servicios NSSM en Windows Server y runbook. |
| **Calidad** | `mypy --strict`, Ruff (incluye reglas de seguridad) y más de 90 casos de prueba: unitarias, API, E2E con navegador real e integración con RabbitMQ y PostgreSQL. CI en Python 3.11, 3.12 y 3.13. |

## Arquitectura

```mermaid
flowchart LR
    CSV[(Lote CSV)] --> P[colmena-carga]
    P -- registra PENDING --> DB[(PostgreSQL)]
    P -- publica --> EX{{rpa.tasks}}
    EX --> Q[[rpa.payment_agreement]]
    Q --> W1[obrera Linux]
    Q --> W2[obrera Windows]
    W1 & W2 -- Playwright --> PORTAL[Aplicativo web]
    W1 & W2 -- falla técnica --> RQ[[espera 10s / 60s / 300s]]
    RQ -- TTL vencido --> EX
    W1 & W2 -- error de negocio --> DLQ[[DLQ]]
    W1 & W2 -- estado, eventos, latidos --> DB
    M[colmena-monitor · FastAPI] --> DB
    M -- reprocesar --> EX
    OPS((Operación)) --> M
    PROM[Prometheus] -- /metrics --> M
```

El núcleo de la obrera (`TaskProcessor`) **no conoce RabbitMQ**: recibe un mensaje y devuelve un
desenlace (`ACK`, `RETRY` o `DEAD`). El adaptador de pika lo traduce a operaciones del broker. Así
toda la lógica de reintentos e idempotencia se prueba en milisegundos sin infraestructura.
Detalle completo en [docs/architecture.md](docs/architecture.md).

```mermaid
stateDiagram-v2
    direction LR
    [*] --> PENDING
    PENDING --> RUNNING
    RUNNING --> DONE
    RUNNING --> RETRYING: error técnico
    RETRYING --> RUNNING: vence TTL
    RUNNING --> FAILED: error de negocio / sin intentos
    FAILED --> PENDING: reproceso
```

## Inicio rápido

### Con Docker (plataforma completa)

```bash
git clone https://github.com/DarwinMontiel/colmena-rpa.git
cd colmena-rpa
docker compose up --build -d     # postgres, rabbitmq, migraciones, portal, 2 obreras, monitor
docker compose run --rm carga colmena-carga encolar --archivo data/sample_tasks.csv
```

- Panel de operación: <http://localhost:8000> · API: <http://localhost:8000/docs>
- RabbitMQ: <http://localhost:15672> (guest/guest): mira las colas de espera y la DLQ en acción
- Portal demo: <http://localhost:8001>: falla con 503 el 15 % de las veces para ejercitar reintentos
- Más obreras: `docker compose up -d --scale obrera=4`

### Desarrollo local

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
make install        # dependencias + Chromium + pre-commit
make infra          # solo PostgreSQL y RabbitMQ en Docker
make migrate
colmena-obrera      # en otra terminal: colmena-monitor
```

### Formato del lote

```csv
documento,cuotas,valor_cuota,fecha_primer_pago
1012345678,6,300000,+7d
```

Las columnas que empiezan por `fecha` aceptan fechas ISO (`2027-01-15`) o relativas a la carga:
`hoy`, `hoy+15`, `+15d`, `-3d`. Con `--simular` se valida el archivo sin publicar nada.

| Comando | Para qué |
|---|---|
| `colmena-carga encolar --archivo lote.csv [--proceso X] [--lote ID] [--simular]` | Registrar y publicar un lote |
| `colmena-obrera` | Iniciar una obrera (consume los procesos de `RPA_PROCESSES`) |
| `colmena-monitor` | API, panel de operación y métricas |

Los nombres de la v1 (`rpa-worker`, `rpa-producer enqueue --file`, `rpa-monitor`) siguen
funcionando como alias.

## Pruebas

| Suite | Comando | Qué valida |
|---|---|---|
| Unitarias + API | `make test` | Política de reintentos, topología, publicación, procesador, adaptador pika, repositorios, latidos, configuración, endpoints, métricas, migraciones vs. modelo y el lote de ejemplo contra el portal |
| E2E | `make e2e` | El bot real con Chromium inicia sesión, busca el cliente, registra el acuerdo, es idempotente y guarda evidencia |
| Integración | `make integration` | Obrera real contra RabbitMQ y PostgreSQL: éxito, reintento por TTL y DLQ de punta a punta |

Las tres suites corren en [GitHub Actions](.github/workflows/ci.yml) en cada push, junto con
Ruff, mypy y el build de la imagen Docker.

## Configuración

Todo se configura por variables de entorno con prefijo `RPA_` (ver [.env.example](.env.example)).
Las listas se escriben separadas por comas para que el mismo archivo sirva en Docker, systemd y
NSSM.

| Variable | Por defecto | Descripción |
|---|---|---|
| `RPA_DATABASE_URL` | `postgresql+psycopg://rpa:rpa@localhost:5432/rpa` | Conexión a PostgreSQL |
| `RPA_AMQP_URL` | `amqp://guest:guest@localhost:5672/%2F` | Conexión a RabbitMQ |
| `RPA_PROCESSES` | `payment_agreement` | Procesos (colas) que consume esta obrera |
| `RPA_MAX_ATTEMPTS` | `4` | Intentos totales antes de la DLQ |
| `RPA_RETRY_DELAYS_SECONDS` | `10,60,300` | Espera entre intentos |
| `RPA_HEARTBEAT_INTERVAL_SECONDS` | `15` | Frecuencia del latido |
| `RPA_OFFLINE_AFTER_SECONDS` | `60` | Umbral para marcar una obrera «Sin latido» |
| `RPA_REQUEUE_PENDING_AFTER_SECONDS` | `900` | Antigüedad mínima para reprocesar una tarea pendiente |
| `RPA_PORTAL_URL` / `_USER` / `_PASSWORD` | demo | Aplicativo que opera el bot |

## Estructura

```
src/colmena_rpa/
├── domain/          # modelos, reglas y errores (sin dependencias de infraestructura)
├── messaging/       # topología RabbitMQ, publicación con confirms, política de reintentos
├── persistence/     # SQLAlchemy Core, repositorios, esquema
├── bots/            # contrato Bot, registro y bot de acuerdos de pago (Playwright)
├── worker/          # procesador (núcleo), adaptador pika, latidos
├── producer/        # CLI colmena-carga y lector de lotes
├── monitor/         # API FastAPI, métricas Prometheus y panel (HTML/CSS/JS)
└── demo_portal/     # portal de cartera simulado para demos y pruebas E2E
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
| [0004](docs/adr/0004-clasificacion-de-errores-rpa.md) | Errores de negocio vs. técnicos, al estilo Blue Prism |
| [0005](docs/adr/0005-monitoreo-por-heartbeats.md) | Monitoreo por latidos en PostgreSQL |

## Qué demuestra y cómo se relaciona con mi experiencia

Como desarrollador RPA en una fintech de gestión de cartera construyo bots en Python y Playwright
que operan portales sin API, y bots de prevalidación sobre RabbitMQ con colas prioritarias,
ACK/NACK y dead-letter queues. Colmena RPA reúne esos patrones en un proyecto abierto, con datos
ficticios y un portal simulado, para mostrar las decisiones que importan cuando un bot pasa de
«funciona en mi máquina» a operar todos los días:

- **No perder casos ni duplicarlos**: *at-least-once*, `ack` después de persistir, reclamo
  atómico, referencia idempotente y una regla de reproceso que evita mensajes dobles.
- **Separar lo que se reintenta de lo que se escala**: un 503 se reintenta con espera; un cliente
  inexistente o un acuerdo que no cubre el mínimo pasa a revisión de cartera con evidencia.
- **Operar en servidores mixtos**: servicios systemd y NSSM, parada ordenada, latidos y runbook.
- **Diseño que se puede probar**: núcleo sin broker, pruebas en milisegundos y E2E con navegador.

## Proyectos relacionados

| Repositorio | Relación |
|---|---|
| [torre-de-control](https://github.com/DarwinMontiel/torre-de-control) | Monitoreo en tiempo real (TypeScript, Fastify, Redis, WebSocket) que vigila las colas de Colmena RPA. El panel de este repositorio es el de la operación diaria; la torre es el monitoreo dedicado. |
| [vigia-ocr](https://github.com/DarwinMontiel/vigia-ocr) | Bot hermano con Selenium, OCR y SQL Server. |
| [faro-cobranza](https://github.com/DarwinMontiel/faro-cobranza) | CRM de cobranza con acuerdos de pago y API REST para bots. |
| [radar-cartera](https://github.com/DarwinMontiel/radar-cartera) | ETL y analítica de cartera con reglas de calidad de datos e indicadores. |

## Hoja de ruta

- [ ] Autenticación del monitor con OIDC (Azure AD / Keycloak).
- [ ] Programación de lotes (cron) desde el monitor.
- [ ] Panel de Grafana versionado como código.
- [ ] Bot de descarga de soportes con validación de archivos.

## Autor

**Darwin Montiel Mora**: desarrollador RPA & Backend · Ingeniería de Sistemas
[LinkedIn](https://www.linkedin.com/in/darwin-montiel-mora-925216206) · [GitHub](https://github.com/DarwinMontiel)

Licencia [MIT](LICENSE).
