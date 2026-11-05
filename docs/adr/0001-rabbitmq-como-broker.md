# ADR-0001 · RabbitMQ como broker de tareas

- **Estado:** aceptada
- **Fecha:** 2026-11

## Contexto

Los bots deben repartirse el trabajo entre varios servidores (Windows y Linux), sobrevivir a la
caída de cualquiera de ellos y procesar cada tarea al menos una vez. Opciones evaluadas:

| Opción | A favor | En contra |
|---|---|---|
| Tabla en PostgreSQL como cola (`SELECT … FOR UPDATE SKIP LOCKED`) | Una pieza menos de infraestructura | *Polling* constante, reintentos con espera hechos a mano, sin DLQ nativa |
| Redis (listas / streams) | Muy rápido, simple | Durabilidad configurable pero no es su fuerte; DLQ y reintentos manuales |
| Kafka | Throughput enorme, *replay* | Sobredimensionado para cientos de tareas/hora; sin *ack* por mensaje ni TTL por cola |
| **RabbitMQ** | *Ack* manual por mensaje, *prefetch*, DLX, TTL, colas quorum, UI de administración | Una pieza más que operar |

## Decisión

Usar **RabbitMQ** con:

- Un exchange `direct` (`rpa.tasks`) y una cola por proceso (`rpa.<proceso>`), tipo **quorum**
  para replicación y durabilidad en un cluster.
- `prefetch_count = 1` y *ack* manual: cada worker toma una tarea a la vez (*competing consumers*).
- Mensajes persistentes y *publisher confirms* en el productor.

## Consecuencias

- Escalar es levantar más workers; RabbitMQ reparte la carga sin configuración adicional.
- Reintentos con espera y DLQ se resuelven con primitivas del broker ([ADR-0002](0002-reintentos-con-colas-ttl.md)).
- Se agrega RabbitMQ a la operación: se incluye en `docker-compose.yml`, en CI (*service
  container*) y en el [runbook](../runbook.md).
