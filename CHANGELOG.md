# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y
[SemVer](https://semver.org/lang/es/).

## [1.0.0] - 2026-11-05

### Agregado
- Worker RPA con consumo de RabbitMQ (`prefetch=1`, *ack* manual, reconexión con backoff y
  parada ordenada en Linux y Windows).
- Topología por proceso: cola principal quorum, colas de espera con TTL (10 s / 60 s / 300 s) y DLQ.
- Clasificación de errores de negocio vs. sistema y política de reintentos configurable.
- Persistencia en PostgreSQL con bitácora de eventos por tarea y migraciones Alembic.
- Bot `payment_agreement` con Playwright: login, búsqueda de cliente, registro de acuerdo de
  pago idempotente y captura de evidencia ante fallas.
- Productor CLI con `task_id` determinístico para evitar duplicados por recarga de archivos.
- Monitor FastAPI: KPIs, salud de workers por latidos, tareas, bitácora, reproceso y `/metrics`.
- Dashboard web (HTML/CSS/JS sin frameworks) con modo demo publicado en GitHub Pages.
- Portal de cartera simulado con inyección de fallas para demos y pruebas E2E.
- Docker Compose, unidades systemd, script de servicios Windows (NSSM) y CI en GitHub Actions.

[1.0.0]: https://github.com/DarwinMontiel/colmena-rpa/releases/tag/v1.0.0
