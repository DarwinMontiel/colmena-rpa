"""Lectura de archivos de entrada y conversión a ``TaskMessage``.

Las columnas cuyo nombre empieza por ``fecha`` aceptan fechas absolutas (``2026-12-01``) o
relativas al día de carga: ``hoy``, ``hoy+15``, ``+15d`` o ``-3d``. Así el lote de ejemplo
nunca queda con fechas vencidas, sin importar cuándo se pruebe.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from colmena_rpa.domain.models import TaskMessage

#: Espacio de nombres fijo de Colmena RPA para derivar ``task_id`` (UUID v5, RFC 9562).
TASK_NAMESPACE = UUID("6f1c7a52-3d4e-5b8a-9c0d-2e7f4a1b9c35")

_RELATIVE_DATE = re.compile(r"^(?:hoy)?\s*(?:([+-])\s*(\d{1,4})\s*d?)?$", re.IGNORECASE)


def _coerce(value: str) -> Any:
    value = value.strip()
    for cast in (int, float):
        try:
            return cast(value)
        except ValueError:
            continue
    return value


def resolve_date(value: str, today: date) -> str:
    """Convierte ``hoy``, ``hoy+N``, ``+Nd`` o ``-Nd`` en fecha ISO; deja igual lo demás."""
    text = value.strip()
    if not text:
        return text
    match = _RELATIVE_DATE.match(text)
    if match is None or not (text.lower().startswith("hoy") or match.group(1)):
        return text
    sign, days = match.group(1), int(match.group(2) or 0)
    offset = timedelta(days=-days if sign == "-" else days)
    return (today + offset).isoformat()


def deterministic_task_id(process: str, row: dict[str, Any]) -> UUID:
    """Misma fila con el mismo contenido = misma tarea (evita duplicados por recarga).

    Se usa un UUID v5 real (SHA-1 con un espacio de nombres propio). Las fechas relativas se
    resuelven antes de calcular el identificador: la identidad de la tarea es el acuerdo
    concreto (documento, cuotas, valor y fecha), no el texto del archivo.
    """
    canonical = process + "|" + "|".join(f"{k}={row[k]}" for k in sorted(row))
    return uuid5(TASK_NAMESPACE, canonical)


def read_tasks(
    path: Path, process: str, batch_id: str, today: date | None = None
) -> Iterator[TaskMessage]:
    reference_day = today or date.today()
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            payload: dict[str, Any] = {}
            for raw_key, raw_value in row.items():
                if not raw_key or raw_value is None:
                    continue
                key = raw_key.strip()
                if key.lower().startswith("fecha"):
                    payload[key] = resolve_date(raw_value, reference_day)
                elif key == "documento":
                    # Identificador, no número: se conservan los ceros a la izquierda.
                    payload[key] = raw_value.strip()
                else:
                    payload[key] = _coerce(raw_value)
            yield TaskMessage(
                task_id=deterministic_task_id(process, payload),
                process=process,
                payload=payload,
                correlation_id=batch_id,
            )
