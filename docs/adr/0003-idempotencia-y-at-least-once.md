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

1. **Carga**: `task_id` determinístico = UUID v5 (`uuid.uuid5`, SHA-1 con un espacio de nombres
   propio de Colmena) del proceso + contenido de la fila. Cargar dos veces el mismo archivo no
   crea tareas nuevas (`INSERT … ON CONFLICT DO NOTHING`). Las fechas relativas del CSV
   (`+7d`, `hoy+15`) se resuelven **antes** de calcular el identificador: la identidad es el
   acuerdo concreto, así que recargar el mismo archivo el mismo día es idempotente y cargarlo
   otro día produce acuerdos con otra fecha (tareas distintas, como corresponde).
2. **Obrera**: antes de ejecutar reclama la tarea con un `UPDATE` condicional
   (`status NOT IN ('DONE','FAILED')`); si la tarea ya está en estado final, se
   confirma el mensaje sin ejecutar el bot.
3. **Aplicativo**: el bot envía `referencia = task_id`; el portal devuelve la confirmación
   existente si la referencia ya fue registrada.

## Consecuencias

- Si una obrera muere a mitad de la tarea, otra la retoma (estado `RUNNING` no es final).
- La capa 3 depende de que el aplicativo acepte una referencia externa. Para aplicativos que no
  la soporten, el bot debe consultar antes de crear (búsqueda por documento + fecha).
- La ventana de duplicado entre "publicar reintento" y "ack" queda cubierta por las capas 2 y 3.
- La v2.0.0 cambió la derivación del `task_id` (antes: SHA-256 truncado con la versión 5
  forzada, que no era un UUID v5 real). Recargar en la v2 un archivo cargado con la v1 genera
  identificadores nuevos; por eso el cambio se publicó en una versión mayor.
