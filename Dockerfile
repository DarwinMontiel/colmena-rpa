# syntax=docker/dockerfile:1.7
# Imagen única para worker, monitor, productor y portal demo (cambia solo el comando).

FROM python:3.12-slim AS base
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
COPY --from=build /wheels /wheels
RUN pip install /wheels/*.whl && rm -rf /wheels \
    && playwright install --with-deps chromium \
    && useradd --create-home --uid 10001 rpa \
    && mkdir -p /app/artifacts && chown rpa:rpa /app/artifacts
COPY alembic.ini ./
COPY alembic ./alembic
COPY data ./data
USER rpa
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import sys,urllib.request; sys.exit(0)" || exit 1
CMD ["rpa-worker"]
