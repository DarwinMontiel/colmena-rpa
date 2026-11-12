from __future__ import annotations

from datetime import date
from pathlib import Path
from uuid import uuid5

import pytest

from colmena_rpa.bots.registry import BotRegistry
from colmena_rpa.domain.errors import UnknownProcessError
from colmena_rpa.producer.loader import (
    TASK_NAMESPACE,
    deterministic_task_id,
    read_tasks,
    resolve_date,
)
from tests.conftest import ScriptedBot


class TestRegistry:
    def test_bot_is_created_lazily_and_set_up_once(self) -> None:
        bot = ScriptedBot([])
        registry = BotRegistry()
        registry.register("scripted", lambda: bot)

        assert bot.setups == 0
        assert registry.get("scripted") is registry.get("scripted")
        assert bot.setups == 1

    def test_close_all_tears_down_instances(self) -> None:
        bot = ScriptedBot([])
        registry = BotRegistry()
        registry.register("scripted", lambda: bot)
        registry.get("scripted")
        registry.close_all()
        assert bot.teardowns == 1

    def test_unknown_process_raises_business_error(self) -> None:
        with pytest.raises(UnknownProcessError):
            BotRegistry().get("nope")

    def test_duplicate_registration_is_rejected(self) -> None:
        registry = BotRegistry()
        registry.register("a", lambda: ScriptedBot([]))
        with pytest.raises(ValueError, match="ya está registrado"):
            registry.register("a", lambda: ScriptedBot([]))


class TestLoader:
    def test_reads_rows_and_keeps_document_as_string(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "lote.csv"
        csv_file.write_text(
            "documento,cuotas,valor_cuota,fecha_primer_pago\n0012345678,6,250000.5,2026-12-01\n",
            encoding="utf-8",
        )
        [msg] = list(read_tasks(csv_file, "payment_agreement", "lote-1"))

        assert msg.payload == {
            "documento": "0012345678",
            "cuotas": 6,
            "valor_cuota": 250000.5,
            "fecha_primer_pago": "2026-12-01",
        }
        assert msg.correlation_id == "lote-1"

    def test_task_id_is_deterministic(self) -> None:
        row = {"documento": "1", "cuotas": 2}
        assert deterministic_task_id("p", row) == deterministic_task_id(
            "p", dict(reversed(row.items()))
        )
        assert deterministic_task_id("p", row) != deterministic_task_id("q", row)

    def test_task_id_is_a_real_uuid5(self) -> None:
        row = {"documento": "1", "cuotas": 2}
        task_id = deterministic_task_id("p", row)
        assert task_id.version == 5
        assert task_id == uuid5(TASK_NAMESPACE, "p|cuotas=2|documento=1")

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("+15d", "2026-12-16"),
            ("+15", "2026-12-16"),
            ("-3d", "2026-11-28"),
            ("hoy", "2026-12-01"),
            ("HOY+30", "2026-12-31"),
            ("hoy + 2 d", "2026-12-03"),
            ("2027-01-15", "2027-01-15"),
            ("15", "15"),
            ("mañana", "mañana"),
            ("", ""),
        ],
    )
    def test_resolve_relative_dates(self, value: str, expected: str) -> None:
        assert resolve_date(value, date(2026, 12, 1)) == expected

    def test_relative_dates_are_resolved_before_hashing(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "lote.csv"
        csv_file.write_text(
            "documento,cuotas,valor_cuota,fecha_primer_pago\n1,6,250000,+10d\n", encoding="utf-8"
        )
        [monday] = list(read_tasks(csv_file, "p", "l", today=date(2026, 12, 7)))
        [tuesday] = list(read_tasks(csv_file, "p", "l", today=date(2026, 12, 8)))

        assert monday.payload["fecha_primer_pago"] == "2026-12-17"
        assert tuesday.payload["fecha_primer_pago"] == "2026-12-18"
        assert monday.task_id != tuesday.task_id  # acuerdos distintos: fechas distintas
        [again] = list(read_tasks(csv_file, "p", "otro-lote", today=date(2026, 12, 7)))
        assert again.task_id == monday.task_id  # misma carga el mismo día: idempotente

    @pytest.mark.parametrize("today", [date.today(), date(2031, 6, 30)])
    def test_sample_file_never_expires(self, today: date) -> None:
        sample = Path(__file__).parents[2] / "data" / "sample_tasks.csv"
        messages = list(read_tasks(sample, "payment_agreement", "x", today=today))
        assert len(messages) >= 5
        assert len({m.task_id for m in messages}) == len(messages)
        for message in messages:
            assert date.fromisoformat(message.payload["fecha_primer_pago"]) > today
