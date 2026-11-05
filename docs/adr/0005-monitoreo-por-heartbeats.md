# ADR-0005 · Monitoreo de bots por latidos en PostgreSQL

- **Estado:** aceptada
- **Fecha:** 2026-11

## Contexto

Operación necesita saber en todo momento qué bots están vivos, qué están haciendo y cuántas
tareas llevan, en servidores Windows y Linux distintos, sin instalar agentes adicionales.

## Decisión

- Cada worker ejecuta un hilo que hace *upsert* en `bot_heartbeats` cada 15 s (y en cada cambio
  de estado): host, plataforma, estado (`IDLE`/`BUSY`/`STOPPING`), tarea actual y contadores.
- El monitor calcula la salud: `ONLINE` si el último latido tiene menos de
  `RPA_OFFLINE_AFTER_SECONDS` (60 s por defecto), si no `OFFLINE`.
- Las métricas se calculan en cada *scrape* de Prometheus a partir de la base de datos (el
  monitor no guarda estado en memoria y puede tener varias réplicas).
- Una falla al escribir el latido se registra pero nunca detiene al worker.

## Consecuencias

- Sin dependencias extra: la misma base de datos que ya guarda las tareas.
- La alerta "bot caído" se define en Prometheus/Grafana sobre `rpa_bot_up == 0`.
- Con cientos de workers convendría mover los latidos a un almacén de series de tiempo; para
  decenas de bots PostgreSQL es más que suficiente.
