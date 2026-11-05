# Runbook de operación

Procedimientos para soporte diario de la plataforma. Cada sección: **síntoma → diagnóstico → acción**.

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

-- Tareas atascadas en RUNNING más de 15 minutos (worker caído a mitad de tarea)
SELECT id, worker_id, started_at FROM tasks
WHERE status = 'RUNNING' AND started_at < now() - interval '15 minutes';

-- Bitácora completa de una tarea
SELECT at, event, attempt, worker_id, detail FROM task_events
WHERE task_id = '<uuid>' ORDER BY id;
```

## 1. Un bot aparece OFFLINE

1. Verificar el servicio en el servidor:
   - Linux: `systemctl status rpa-worker@1` y `journalctl -u rpa-worker@1 -n 200`.
   - Windows: `Get-Service rpa-worker-*` y `C:\rpa-orchestrator\logs\rpa-worker-1.log`.
2. Si el proceso está vivo pero no reporta, revisar conectividad a PostgreSQL (`heartbeat.failed`
   en los logs).
3. Reiniciar el servicio. La tarea que tenía en curso vuelve a la cola automáticamente (no se
   confirmó) y otro worker la retoma.

## 2. La DLQ crece

1. En el dashboard filtrar **Fallidas** y abrir la tarea: el último error y la bitácora indican
   la causa. La evidencia (captura) está en `artifacts/<task_id>-attempt<N>.png`.
2. Clasificar:
   - **Error de negocio** (cliente inexistente, monto insuficiente): escalar a negocio con el
     listado; no reprocesar hasta corregir el dato de origen.
   - **Intentos agotados por falla del portal**: confirmar que el portal ya responde y usar
     **Reprocesar tarea** en el dashboard (o `POST /api/tasks/{id}/requeue`).
3. Los mensajes de la DLQ se pueden purgar desde la UI de RabbitMQ una vez reprocesados: el
   estado de verdad está en PostgreSQL.

## 3. El portal está caído

- Los workers seguirán reintentando con espera (10 s, 60 s, 300 s) y luego enviarán a la DLQ.
- Si la caída será larga, detener los workers (`systemctl stop rpa-worker@*`) para que las
  tareas esperen en la cola principal sin consumir intentos; al volver el portal, iniciarlos.

## 4. Credenciales del portal rechazadas

- Síntoma: errores `credenciales del portal rechazadas` en muchas tareas.
- Actualizar `RPA_PORTAL_PASSWORD` en `/etc/rpa-orchestrator/worker.env` (Linux) o en el
  `worker.env` del servidor Windows y reiniciar los servicios. Reprocesar las fallidas.

## 5. Tareas atascadas en RUNNING

- Ocurre si un worker murió sin que RabbitMQ lo detectara todavía. El broker reentrega el
  mensaje al cerrar la conexión (máx. ~2 latidos AMQP, 120 s).
- Si persisten tras 15 min: verificar en la UI de RabbitMQ que la cola no tenga mensajes
  *unacked* de una conexión muerta y, si es necesario, cerrar esa conexión desde la UI.

## 6. Escalar la capacidad

- Docker: `docker compose up -d --scale worker=4`.
- Linux: `systemctl enable --now rpa-worker@3`.
- Windows: `.\deploy\windows\install-service.ps1 -Version <tag> -Instances 3`.
- Regla práctica: el límite lo pone el aplicativo operado, no el broker. Subir de a un worker y
  observar la tasa de 503/timeouts en el dashboard.

## 7. Alertas recomendadas (Prometheus)

```yaml
groups:
  - name: rpa
    rules:
      - alert: RpaBotDown
        expr: rpa_bot_up == 0
        for: 2m
        labels: { severity: warning }
        annotations: { summary: "El worker {{ $labels.worker }} no reporta latido" }
      - alert: RpaFailedTasksGrowing
        expr: increase(rpa_tasks{status="FAILED"}[1h]) > 20
        labels: { severity: critical }
        annotations: { summary: "Más de 20 tareas fallidas en la última hora" }
```
