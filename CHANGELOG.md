# Registro de cambios

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y
[SemVer](https://semver.org/lang/es/).

## [2.0.0] - 2026-11-12

El proyecto pasa a llamarse **Colmena RPA** (antes `rpa-orchestrator`).

### Cambiado (incompatible)
- Paquete Python `rpa_orchestrator` → `colmena_rpa`; distribución `colmena-rpa`.
- Comandos `colmena-obrera`, `colmena-carga encolar --archivo` y `colmena-monitor`. Los nombres
  de la v1 (`rpa-worker`, `rpa-producer enqueue --file`, `rpa-monitor`) quedan como alias.
- Servicios `colmena-obrera@N` / `colmena-monitor` (systemd) y `colmena-obrera-N` (NSSM),
  usuario `colmena` y rutas `/opt/colmena-rpa`, `/etc/colmena-rpa`, `C:\colmena-rpa`. Ver
  «Migrar desde la v1» en `docs/deployment.md`.
- Servicios de docker compose `obrera` y `carga` (antes `worker` y `producer`).
- `task_id` derivado con `uuid.uuid5` y un espacio de nombres propio (antes: SHA-256 truncado
  con la versión forzada). Un archivo de la v1 recargado en la v2 genera identificadores nuevos.
- Sin cambios: esquema de base de datos, colas y exchange `rpa.*`, métricas `rpa_*` y
  variables `RPA_*`.

### Agregado
- Fechas relativas en los lotes CSV (`hoy`, `hoy+N`, `+Nd`, `-Nd`); el lote de ejemplo ya no
  vence. Prueba que recorre el lote contra el portal en dos fechas.
- Panel de operación en español con identidad de Colmena: estados traducidos, sección Obreras,
  resumen del acuerdo en pesos colombianos y clasificación del error (negocio o técnico).
- `can_requeue` en el detalle de tarea y `RPA_REQUEUE_PENDING_AFTER_SECONDS`.
- CI en Python 3.11, 3.12 y 3.13; healthchecks HTTP reales en docker compose.

### Corregido
- La obrera quedaba colgada en BUSY y el mensaje sin confirmar si el procesamiento fallaba por
  infraestructura (p. ej. PostgreSQL caído): ahora se reencola con `nack` tras una pausa.
- Reprocesar una tarea PENDING cuyo mensaje seguía en la cola publicaba un duplicado; además el
  reclamo de la tarea en la obrera es atómico y el reproceso resiste el doble clic.
- Si el broker fallaba durante un reproceso, la tarea quedaba con 0 intentos en la bitácora.
- `.env.example` con listas JSON se rompía al pasar por `source` de bash y por `EnvironmentFile`
  de systemd; las listas aceptan ahora valores separados por comas.
- El `HEALTHCHECK` de la imagen siempre devolvía éxito; se reemplazó por healthchecks reales.
- La alerta de Prometheus usaba `increase()` sobre un *gauge*; ahora usa `delta()`.

## [1.0.0] - 2026-11-05

### Agregado
- Obrera (worker) RPA con consumo de RabbitMQ (`prefetch=1`, *ack* manual, reconexión con
  backoff y parada ordenada en Linux y Windows).
- Topología por proceso: cola principal quorum, colas de espera con TTL (10 s / 60 s / 300 s) y DLQ.
- Clasificación de errores de negocio vs. técnicos y política de reintentos configurable.
- Persistencia en PostgreSQL con bitácora de eventos por tarea y migraciones Alembic.
- Bot `payment_agreement` con Playwright: inicio de sesión, búsqueda de cliente, registro de
  acuerdo de pago idempotente y captura de evidencia ante fallas.
- CLI de carga con `task_id` determinístico para evitar duplicados por recarga de archivos.
- Monitor FastAPI: indicadores, salud de las obreras por latidos, tareas, bitácora, reproceso y
  `/metrics`.
- Panel web (HTML/CSS/JS sin frameworks) con modo demo publicado en GitHub Pages.
- Portal de cartera simulado con inyección de fallas para demos y pruebas E2E.
- Docker Compose, unidades systemd, script de servicios Windows (NSSM) y CI en GitHub Actions.

[2.0.0]: https://github.com/DarwinMontiel/colmena-rpa/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/DarwinMontiel/colmena-rpa/releases/tag/v1.0.0
