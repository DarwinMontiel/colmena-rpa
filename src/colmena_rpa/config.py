"""Configuración centralizada (12-factor): todo se lee de variables de entorno con prefijo RPA_."""

from __future__ import annotations

import json
import socket
from functools import lru_cache
from typing import Annotated, Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RPA_", env_file=".env", extra="ignore")

    # Infraestructura
    database_url: str = "postgresql+psycopg://rpa:rpa@localhost:5432/rpa"
    amqp_url: str = "amqp://guest:guest@localhost:5672/%2F"
    exchange: str = "rpa.tasks"

    # Worker
    worker_id: str = Field(default_factory=lambda: f"{socket.gethostname()}-worker")
    processes: Annotated[list[str], NoDecode] = ["payment_agreement"]
    prefetch_count: int = 1
    max_attempts: int = 4
    retry_delays_seconds: Annotated[list[int], NoDecode] = [10, 60, 300]
    heartbeat_interval_seconds: int = 15
    artifacts_dir: str = "artifacts"

    # Monitor
    offline_after_seconds: int = 60
    # Una tarea PENDING solo se puede reprocesar si lleva este tiempo sin cambios (evita
    # republicar un mensaje que todavía espera en la cola).
    requeue_pending_after_seconds: int = 900

    # Bot de acuerdos de pago (portal demo incluido en el repositorio)
    portal_url: str = "http://localhost:8001"
    portal_user: str = "bot"
    portal_password: str = "bot-demo"  # noqa: S105 - credencial del portal demo, se sobreescribe por entorno
    headless: bool = True
    browser_timeout_ms: int = 15_000

    # Observabilidad
    log_level: str = "INFO"
    log_json: bool = True

    @field_validator("processes", "retry_delays_seconds", mode="before")
    @classmethod
    def _split_list(cls, value: Any) -> Any:
        """Acepta listas JSON (``["a","b"]``) o separadas por comas (``a,b``).

        La forma con comas sobrevive intacta a ``source`` de bash, a ``EnvironmentFile`` de
        systemd y a NSSM, que quitan o conservan comillas de manera distinta.
        """
        if not isinstance(value, str):
            return value
        text = value.strip()
        if text.startswith("["):
            return json.loads(text)
        return [item.strip().strip("\"'") for item in text.split(",") if item.strip()]

    @field_validator("retry_delays_seconds")
    @classmethod
    def _delays_not_empty(cls, value: list[int]) -> list[int]:
        if not value or any(d <= 0 for d in value):
            raise ValueError("retry_delays_seconds debe tener al menos un valor positivo")
        return value

    @field_validator("max_attempts")
    @classmethod
    def _attempts_positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("max_attempts debe ser >= 1")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
