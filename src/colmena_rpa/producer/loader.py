"""Lectura de archivos de entrada y conversión a ``TaskMessage``."""

from __future__ import annotations

import csv
import hashlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID

from colmena_rpa.domain.models import TaskMessage


def _coerce(value: str) -> Any:
    value = value.strip()
    for cast in (int, float):
        try:
            return cast(value)
        except ValueError:
            continue
    return value


def deterministic_task_id(process: str, row: dict[str, Any]) -> UUID:
    """Mismo archivo cargado dos veces = mismas tareas (evita duplicados por recarga)."""
    canonical = process + "|" + "|".join(f"{k}={row[k]}" for k in sorted(row))
    return UUID(bytes=hashlib.sha256(canonical.encode()).digest()[:16], version=5)


def read_tasks(path: Path, process: str, batch_id: str) -> Iterator[TaskMessage]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            payload = {k.strip(): _coerce(v) for k, v in row.items() if k and v is not None}
            # Los documentos son identificadores, no números.
            if "documento" in payload:
                payload["documento"] = str(row["documento"]).strip()
            yield TaskMessage(
                task_id=deterministic_task_id(process, payload),
                process=process,
                payload=payload,
                correlation_id=batch_id,
            )
