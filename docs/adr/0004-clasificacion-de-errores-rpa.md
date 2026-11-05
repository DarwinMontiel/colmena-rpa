# ADR-0004 · Clasificación de errores: negocio vs. sistema

- **Estado:** aceptada
- **Fecha:** 2026-11

## Contexto

Herramientas RPA como Blue Prism distinguen *Business Exceptions* (el caso no se puede procesar
por una regla de negocio) de *System Exceptions* (falló la aplicación o la infraestructura).
Tratar ambas igual genera reintentos inútiles o, peor, tareas perdidas.

## Decisión

- `BusinessRuleError`: datos inválidos, cliente inexistente, regla del aplicativo incumplida.
  **No se reintenta.** La tarea pasa a `FAILED` y el mensaje a la DLQ con el motivo.
- `TransientError`: timeouts, 503, sesión rechazada. **Se reintenta** según `RetryPolicy`.
- Cualquier otra excepción se trata como **transitoria**: es preferible reintentar y terminar en
  la DLQ con el error registrado que descartar una tarea por un bug no previsto.
- Tras un error de sistema se destruye la instancia del bot (navegador incluido) para que el
  siguiente intento arranque limpio.
- En todo error el bot guarda una captura de pantalla como evidencia.

## Consecuencias

- Los bots deben traducir explícitamente sus errores conocidos (p. ej. `.error-negocio` en el
  portal → `BusinessRuleError`).
- La DLQ contiene solo casos que requieren a una persona, lo que la hace accionable.
