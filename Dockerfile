# syntax=docker/dockerfile:1.7
# Imagen única de Colmena RPA para obrera, monitor, carga de lotes y portal demo
# (cambia solo el comando). Los healthchecks se definen por servicio en docker-compose.yml.

FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
WORKDIR /app

FROM base AS build
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip wheel --wheel-dir /wheels .

FROM base AS runtime
LABEL org.opencontainers.image.title="colmena-rpa" \
      org.opencontainers.image.description="Bots RPA distribuidos con RabbitMQ y trazabilidad en PostgreSQL" \
      org.opencontainers.image.source="https://github.com/DarwinMontiel/colmena-rpa" \
      org.opencontainers.image.licenses="MIT"
COPY --from=build /wheels /wheels
# libatomic1: el Node empaquetado con Playwright lo necesita y la imagen slim no lo trae.
RUN apt-get update && apt-get install -y --no-install-recommends libatomic1 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --root-user-action=ignore /wheels/*.whl && rm -rf /wheels \
    && playwright install --with-deps chromium \
    && useradd --create-home --uid 10001 colmena \
    && mkdir -p /app/artifacts && chown colmena:colmena /app/artifacts
COPY alembic.ini ./
COPY alembic ./alembic
COPY data ./data
USER colmena
EXPOSE 8000
CMD ["colmena-obrera"]
