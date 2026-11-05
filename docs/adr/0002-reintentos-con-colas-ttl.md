# ADR-0002 · Reintentos con colas de espera de TTL fijo

- **Estado:** aceptada
- **Fecha:** 2026-11

## Contexto

La mayoría de fallas de un bot web son transitorias (portal lento, 503, sesión vencida).
Reintentar de inmediato suele volver a fallar y satura el aplicativo. Se necesita espera
creciente (10 s → 60 s → 300 s) sin bloquear al worker.

Alternativas:

1. **`nack` con `requeue=true`**: reintento inmediato e infinito; puede crear bucles calientes.
2. **`time.sleep` en el worker**: bloquea al bot y la conexión AMQP.
3. **TTL por mensaje en una sola cola de espera**: RabbitMQ solo expira mensajes desde la cabeza
   de la cola; un mensaje de 300 s retiene detrás a los de 10 s (*head-of-line blocking*).
4. **Plugin `delayed-message-exchange`**: funciona, pero es un plugin externo no replicado.
5. **Una cola de espera por cada delay, con TTL fijo** y *dead-letter* de regreso al exchange.

## Decisión

Opción 5. Por proceso se declaran `rpa.<proceso>.retry.<N>s` con `x-message-ttl = N·1000`,
`x-dead-letter-exchange = rpa.tasks` y `x-dead-letter-routing-key = <proceso>`.

El worker, ante una falla transitoria con intentos disponibles:

1. Marca la tarea `RETRYING` en PostgreSQL (con el error y el delay).
2. Publica el mensaje con `attempt + 1` en la cola de espera correspondiente.
3. Confirma (`ack`) el mensaje original.

Cuando vence el TTL, RabbitMQ devuelve el mensaje a la cola principal.

## Consecuencias

- Sin plugins, todo con primitivas nativas; los delays se configuran con `RPA_RETRY_DELAYS_SECONDS`.
- Cambiar los delays crea colas nuevas (los argumentos de una cola no se pueden modificar);
  las colas viejas quedan vacías y pueden borrarse.
- El número de intento viaja en el mensaje: la política (`RetryPolicy`) es pura y se prueba
  sin broker.
