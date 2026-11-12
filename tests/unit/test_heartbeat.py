from __future__ import annotations

from uuid import uuid4

from colmena_rpa.domain.models import WorkerState
from colmena_rpa.persistence import HeartbeatRepository
from colmena_rpa.worker.heartbeat import HeartbeatService


def test_heartbeat_tracks_state_and_final_outcomes(heartbeats: HeartbeatRepository) -> None:
    service = HeartbeatService(heartbeats, "w1", ["scripted"], interval_seconds=60)
    task_id = uuid4()

    service.busy(task_id)
    [busy] = heartbeats.all()
    assert (busy.state, busy.current_task_id) == (WorkerState.BUSY, task_id)

    service.idle(True)
    service.idle(None)  # reintento: no cuenta como fallo
    service.idle(False)
    [idle] = heartbeats.all()
    assert (idle.state, idle.tasks_ok, idle.tasks_failed) == (WorkerState.IDLE, 1, 1)
    assert idle.current_task_id is None


def test_heartbeat_failure_never_raises() -> None:
    class Broken:
        def beat(self, _hb: object) -> None:
            raise ConnectionError("db down")

    HeartbeatService(Broken(), "w", [], 1).beat()  # type: ignore[arg-type]
