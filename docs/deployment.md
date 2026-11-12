# Despliegue

Tres formas de desplegar, de la más simple a la más cercana a un entorno corporativo.

## 1. Docker Compose (local / demo)

```bash
docker compose up --build -d
docker compose run --rm carga colmena-carga encolar --archivo data/sample_tasks.csv
```

| Servicio | URL |
|---|---|
| Monitor | http://localhost:8000 (OpenAPI en `/docs`) |
| RabbitMQ | http://localhost:15672 (guest / guest) |
| Portal demo | http://localhost:8001 (bot / bot-demo) |

El servicio `migrate` aplica las migraciones de Alembic antes de iniciar worker y monitor.

## 2. Servidores Linux (systemd)

```bash
sudo ./deploy/linux/install.sh v2.0.0
```

El script:

1. Crea el usuario de sistema `rpa` y clona/actualiza el repositorio en `/opt/colmena-rpa`
   en el *tag* indicado.
2. Crea el entorno virtual, instala el paquete y Chromium para Playwright.
3. Crea `/etc/colmena-rpa/{worker,monitor}.env` a partir de `.env.example` (permisos 640).
4. Aplica migraciones (`alembic upgrade head`).
5. Instala `colmena-monitor.service` y la plantilla `colmena-obrera@.service`, y reinicia los workers
   **de forma escalonada** para no detener toda la capacidad a la vez.

Parada ordenada: systemd envía `SIGTERM`; el worker deja de consumir, termina la tarea en curso,
confirma el mensaje y sale (hasta 300 s).

Publicar el monitor detrás de Nginx con TLS:

```nginx
server {
    listen 443 ssl;
    server_name colmena-monitor.empresa.local;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## 3. Windows Server (servicios con NSSM)

Requisitos: Python 3.12, Git y [NSSM](https://nssm.cc) en el `PATH`. En PowerShell como
administrador:

```powershell
.\deploy\windows\install-service.ps1 -Version v2.0.0 -Instances 2
```

Crea los servicios `colmena-obrera-1..N` con inicio automático, logs rotados en
`C:\colmena-rpa\logs` y parada por `Ctrl+C` (el worker atiende `SIGINT`/`SIGBREAK` y termina
la tarea en curso).

## Proceso de release

1. Integrar a `main` con CI en verde (lint, tipos, unitarias, e2e con Playwright, integración con
   RabbitMQ/PostgreSQL y build de la imagen).
2. Actualizar `CHANGELOG.md` y crear el tag: `git tag -a v1.1.0 -m "v1.1.0" && git push --tags`.
3. Desplegar el tag en un servidor (canary), observar el dashboard 15 minutos y continuar con el
   resto.

## Rollback

- Ejecutar el script de despliegue con el tag anterior (`install.sh v2.0.0`).
- Las migraciones se escriben compatibles hacia atrás (agregar columnas nulas, no renombrar en
  caliente), de modo que la versión anterior funciona con el esquema nuevo. Si una migración no
  lo es, el release lo indica y se ejecuta `alembic downgrade -1` antes del rollback.
