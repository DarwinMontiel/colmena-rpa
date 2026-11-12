from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from colmena_rpa.config import Settings

ROOT = Path(__file__).parents[2]


@pytest.mark.parametrize(
    ("processes", "delays", "expected_processes", "expected_delays"),
    [
        ("payment_agreement", "10,60,300", ["payment_agreement"], [10, 60, 300]),
        ("a, b", "5", ["a", "b"], [5]),
        ('["a","b"]', "[10,60]", ["a", "b"], [10, 60]),
    ],
)
def test_lists_from_environment(
    monkeypatch: pytest.MonkeyPatch,
    processes: str,
    delays: str,
    expected_processes: list[str],
    expected_delays: list[int],
) -> None:
    monkeypatch.setenv("RPA_PROCESSES", processes)
    monkeypatch.setenv("RPA_RETRY_DELAYS_SECONDS", delays)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.processes == expected_processes
    assert settings.retry_delays_seconds == expected_delays


def test_invalid_delays_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RPA_RETRY_DELAYS_SECONDS", "10,-5")
    with pytest.raises(ValidationError, match="al menos un valor positivo"):
        Settings(_env_file=None)  # type: ignore[call-arg]


@pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None, reason="requiere bash de Linux"
)
def test_env_example_survives_bash_source(tmp_path: Path) -> None:
    """``install.sh`` hace ``source`` del .env antes de migrar: el resultado debe ser válido."""
    script = (
        f"set -a; source '{ROOT / '.env.example'}'; "
        'printf "%s\\n%s\\n" "$RPA_PROCESSES" "$RPA_RETRY_DELAYS_SECONDS"'
    )
    processes, delays = subprocess.run(  # noqa: S603
        ["bash", "-c", script],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
        cwd=tmp_path,
    ).stdout.splitlines()
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        processes=processes,  # type: ignore[arg-type]
        retry_delays_seconds=delays,  # type: ignore[arg-type]
    )
    assert settings.processes == ["payment_agreement"]
    assert settings.retry_delays_seconds == [10, 60, 300]
