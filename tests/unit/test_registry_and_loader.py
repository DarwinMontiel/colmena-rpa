from __future__ import annotations

from pathlib import Path

import pytest

from colmena_rpa.bots.registry import BotRegistry
from colmena_rpa.domain.errors import UnknownProcessError
from colmena_rpa.producer.loader import deterministic_task_id, read_tasks
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

    def test_sample_file_is_valid(self) -> None:
        sample = Path(__file__).parents[2] / "data" / "sample_tasks.csv"
        messages = list(read_tasks(sample, "payment_agreement", "x"))
        assert len(messages) >= 5
        assert len({m.task_id for m in messages}) == len(messages)
