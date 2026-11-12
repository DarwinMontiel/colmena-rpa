from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from colmena_rpa.config import Settings
from colmena_rpa.domain.models import TaskMessage, WorkerState, utcnow
from colmena_rpa.monitor.app import create_app
from colmena_rpa.persistence import HeartbeatRepository, TaskRepository
from colmena_rpa.persistence.repository import Heartbeat


class FakePublisher:
    def __init__(self) -> None:
        self.sent: list[TaskMessage] = []

    def publish(self, message: TaskMessage) -> None:
        self.sent.append(message)


@pytest.fixture
def publisher() -> FakePublisher:
    return FakePublisher()


@pytest.fixture
def client(settings: Settings, engine, publisher: FakePublisher) -> TestClient:  # type: ignore[no-untyped-def]
    @contextmanager
    def factory() -> Iterator[FakePublisher]:
        yield publisher

    return TestClient(create_app(settings, engine, publisher_factory=factory))


def _beat(repo: HeartbeatRepository, worker_id: str, seconds_ago: int) -> None:
    now = utcnow()
    repo.beat(
        Heartbeat(
            worker_id=worker_id,
            hostname="srv-01",
            platform="Linux 6.8",
            processes=["payment_agreement"],
            state=WorkerState.IDLE,
            current_task_id=None,
            tasks_ok=3,
            tasks_failed=1,
            version="1.0.0",
            started_at=now - timedelta(hours=1),
            last_seen=now - timedelta(seconds=seconds_ago),
        )
    )


def _seed(repo: TaskRepository) -> dict[str, TaskMessage]:
    done = TaskMessage(process="payment_agreement", payload={"documento": "1"})
    failed = TaskMessage(process="payment_agreement", payload={"documento": "2"})
    pending = TaskMessage(process="other_bot")
    for msg in (done, failed, pending):
        repo.register_pending(msg)
    repo.mark_running(done, "w1")
    repo.mark_done(done.task_id, 1, {"confirmation": "AC-9"})
    repo.mark_running(failed, "w1")
    repo.mark_failed(failed.task_id, 1, "BusinessRuleError: no existe")
    return {"done": done, "failed": failed, "pending": pending}


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_summary_counts_and_success_rate(client: TestClient, repo, heartbeats) -> None:  # type: ignore[no-untyped-def]
    _seed(repo)
    _beat(heartbeats, "w-online", 5)
    _beat(heartbeats, "w-offline", 600)

    body = client.get("/api/summary").json()

    assert body["by_status"]["DONE"] == 1
    assert body["by_status"]["FAILED"] == 1
    assert body["by_status"]["PENDING"] == 1
    assert body["success_rate"] == 0.5
    assert body["done_last_hour"] == 1
    assert (body["bots_online"], body["bots_offline"]) == (1, 1)
    assert body["by_process"]["other_bot"] == {"PENDING": 1}


def test_bots_report_health_from_heartbeat_age(client: TestClient, heartbeats) -> None:  # type: ignore[no-untyped-def]
    _beat(heartbeats, "w1", 5)
    _beat(heartbeats, "w2", 120)
    _beat(heartbeats, "w1", 1)  # upsert: no duplica

    bots = {b["worker_id"]: b for b in client.get("/api/bots").json()}

    assert set(bots) == {"w1", "w2"}
    assert bots["w1"]["health"] == "ONLINE"
    assert bots["w2"]["health"] == "OFFLINE"


def test_list_tasks_filters_by_status_and_process(client: TestClient, repo) -> None:  # type: ignore[no-untyped-def]
    seeded = _seed(repo)

    failed = client.get("/api/tasks", params={"status": "FAILED"}).json()
    other = client.get("/api/tasks", params={"process": "other_bot"}).json()

    assert [t["id"] for t in failed] == [str(seeded["failed"].task_id)]
    assert [t["id"] for t in other] == [str(seeded["pending"].task_id)]
    assert client.get("/api/tasks", params={"status": "NOPE"}).status_code == 422


def test_task_detail_includes_audit_trail(client: TestClient, repo) -> None:  # type: ignore[no-untyped-def]
    seeded = _seed(repo)

    body = client.get(f"/api/tasks/{seeded['done'].task_id}").json()

    assert body["output"] == {"confirmation": "AC-9"}
    assert [e["event"] for e in body["events"]] == ["ENQUEUED", "STARTED", "COMPLETED"]
    assert client.get(f"/api/tasks/{uuid4()}").status_code == 404


def test_requeue_failed_task_republishes_it(client: TestClient, repo, publisher) -> None:  # type: ignore[no-untyped-def]
    seeded = _seed(repo)
    task_id = seeded["failed"].task_id

    response = client.post(f"/api/tasks/{task_id}/requeue")

    assert response.status_code == 200
    assert [m.task_id for m in publisher.sent] == [task_id]
    assert client.get(f"/api/tasks/{task_id}").json()["status"] == "PENDING"


def test_requeue_done_task_is_rejected(client: TestClient, repo, publisher) -> None:  # type: ignore[no-untyped-def]
    seeded = _seed(repo)
    response = client.post(f"/api/tasks/{seeded['done'].task_id}/requeue")
    assert response.status_code == 409
    assert publisher.sent == []


def test_prometheus_metrics(client: TestClient, repo, heartbeats) -> None:  # type: ignore[no-untyped-def]
    _seed(repo)
    _beat(heartbeats, "w1", 1)

    text = client.get("/metrics").text

    assert 'rpa_tasks{process="payment_agreement",status="DONE"} 1.0' in text
    assert 'rpa_bot_up{worker="w1"} 1.0' in text


def test_dashboard_is_served(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Colmena RPA" in response.text
    assert client.get("/static/app.js").status_code == 200
