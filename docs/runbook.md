# Runbook de operación

Procedimientos para el soporte diario de Colmena RPA. Cada sección: **síntoma → diagnóstico →
acción**.

## Consultas útiles (PostgreSQL)

```sql
-- Estado del día por proceso
SELECT process, status, count(*)
FROM tasks WHERE created_at >= current_date
GROUP BY 1, 2 ORDER BY 1, 2;

-- Errores más frecuentes de las últimas 24 h
SELECT left(last_error, 80) AS error, count(*)
FROM tasks WHERE status = 'FAILED' AND finished_at >= now() - interval '24 hours'
GROUP BY 1 ORDER BY 2 DESC LIMIT 10;

-- Tareas atascadas en RUNNING más de 15 minutos (obrera caída a mitad de tarea)
SELECT id, worker_id, started_at FROM tasks
WHERE status = 'RUNNING' AND started_at < now() - interval '15 minutes';

-- Bitácora completa de una tarea
SELECT at, event, attempt, worker_id, detail FROM task_events
WHERE task_id = '<uuid>' ORDER BY id;
```

## 1. Una obrera aparece «Sin latido»

1. Verificar el servicio en el servidor:
   - Linux: `systemctl status colmena-obrera@1` y `journalctl -u colmena-obrera@1 -n 200`.
   - Windows: `Get-Service colmena-obrera-*` y `C:\colmena-rpa\logs\colmena-obrera-1.log`.
2. Si el proceso está vivo pero no reporta, revisar la conectividad a PostgreSQL
   (`heartbeat.failed` en los logs).
3. Reiniciar el servicio. La tarea que tenía en curso vuelve a la cola automáticamente (no se
   confirmó) y otra obrera la retoma.

## 2. La DLQ crece

1. En el panel filtrar **Fallidas** y abrir la tarea: el detalle indica si es un **rechazo de
   negocio** o una **falla técnica**, y la bitácora muestra cada intento. La evidencia (captura)
   está en `artifacts/<task_id>-attempt<N>.png`.
2. Clasificar:
   - **Rechazo de negocio** (cliente inexistente, acuerdo que no cubre el mínimo): escalar a
     cartera con el listado; no reprocesar hasta corregir el dato de origen.
   - **Intentos agotados por falla del portal**: confirmar que el portal ya responde y usar
     **Reprocesar tarea** en el panel (o `POST /api/tasks/{id}/requeue`).
   - El botón solo aparece en tareas **fallidas** o **pendientes con más de 15 min sin
     movimiento** (configurable con `RPA_REQUEUE_PENDING_AFTER_SECONDS`). Una pendiente reciente
     todavía tiene su mensaje en la cola: reprocesarla crearía un duplicado.
3. Los mensajes de la DLQ se pueden purgar desde la UI de RabbitMQ una vez reprocesados: el
   estado de verdad está en PostgreSQL.

## 3. El portal está caído

- Las obreras seguirán reintentando con espera (10 s, 60 s, 300 s) y luego enviarán a la DLQ.
- Si la caída será larga, detener las obreras (`systemctl stop 'colmena-obrera@*'`) para que las
  tareas esperen en la cola principal sin consumir intentos; al volver el portal, iniciarlas.

## 4. Credenciales del portal rechazadas

- Síntoma: errores `credenciales del portal rechazadas` en muchas tareas.
- Actualizar `RPA_PORTAL_PASSWORD` en `/etc/colmena-rpa/worker.env` (Linux) o en el
  `worker.env` del servidor Windows y reiniciar los servicios. Reprocesar las fallidas.

## 5. Tareas atascadas en RUNNING

- Ocurre si una obrera murió sin que RabbitMQ lo detectara todavía. El broker reentrega el
  mensaje al cerrar la conexión (máx. ~2 latidos AMQP, 120 s).
- Si persisten tras 15 min: verificar en la UI de RabbitMQ que la cola no tenga mensajes
  *unacked* de una conexión muerta y, si es necesario, cerrar esa conexión desde la UI.
- Si la base de datos estuvo caída, en los logs aparece `worker.processing_crashed`: la obrera
  devolvió el mensaje a la cola (`nack` con reencolado) tras 5 s y siguió libre. No requiere
  acción; cuando PostgreSQL vuelve, la tarea se procesa normalmente.

## 6. Escalar la capacidad

- Docker: `docker compose up -d --scale obrera=4`.
- Linux: `systemctl enable --now colmena-obrera@3`.
- Windows: `.\deploy\windows\install-service.ps1 -Version <tag> -Instances 3`.
- Regla práctica: el límite lo pone el aplicativo operado, no el broker. Subir de a una obrera y
  observar la tasa de 503/timeouts en el panel.

## 7. Alertas recomendadas (Prometheus)

`rpa_tasks` es un *gauge* (conteo actual por estado), así que el crecimiento se mide con
`delta()` y no con `increase()`, que está pensado para contadores.

```yaml
groups:
  - name: colmena-rpa
    rules:
      - alert: ColmenaObreraSinLatido
        expr: rpa_bot_up == 0
        for: 2m
        labels: { severity: warning }
        annotations: { summary: "La obrera {{ $labels.worker }} no reporta latido" }
      - alert: ColmenaFallidasEnAumento
        expr: delta(rpa_tasks{status="FAILED"}[1h]) > 20
        labels: { severity: critical }
        annotations: { summary: "Más de 20 tareas fallidas nuevas en la última hora" }
```

Para ver las colas en tiempo real (mensajes listos, *unacked*, DLQ) está
[torre-de-control](https://github.com/DarwinMontiel/torre-de-control), el monitoreo dedicado.
