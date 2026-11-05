# ADR-0003 · Entrega *at-least-once* con idempotencia en tres capas

- **Estado:** aceptada
- **Fecha:** 2026-11

## Contexto

Un bot que registra acuerdos de pago no puede perder tareas, pero tampoco puede registrar dos
veces el mismo acuerdo. *Exactly-once* no existe de punta a punta entre un broker, una base de
datos y un aplicativo web de terceros.

## Decisión

Garantizar **at-least-once** (el `ack` se envía solo después de persistir el estado y de
publicar el reintento o la DLQ) y neutralizar duplicados en tres capas:

1. **Carga**: `task_id` determinístico = hash del proceso + contenido de la fila. Cargar dos
   veces el mismo archivo no crea tareas nuevas (`INSERT … ON CONFLICT DO NOTHING`).
2. **Worker**: antes de ejecutar, si la tarea ya está en estado final (`DONE`/`FAILED`) se
   confirma el mensaje sin ejecutar el bot.
3. **Aplicativo**: el bot envía `referencia = task_id`; el portal devuelve la confirmación
   existente si la referencia ya fue registrada.

## Consecuencias

- Si un worker muere a mitad de la tarea, otro la retoma (estado `RUNNING` no es final).
- La capa 3 depende de que el aplicativo acepte una referencia externa. Para aplicativos que no
  la soporten, el bot debe consultar antes de crear (búsqueda por documento + fecha).
- La ventana de duplicado entre "publicar reintento" y "ack" queda cubierta por las capas 2 y 3.
