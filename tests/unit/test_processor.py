from __future__ import annotations

from datetime import timedelta

import pytest

from colmena_rpa.domain.models import TaskMessage, TaskStatus, requeue_allowed, utcnow
from colmena_rpa.persistence import TaskRepository
from colmena_rpa.worker.processor import OutcomeKind
from tests.conftest import ScriptedBot


def test_successful_task_is_acked_and_marked_done(make_processor, repo: TaskRepository, message):
    bot = ScriptedBot(["ok"])
    repo.register_pending(message)

    outcome = make_processor(bot).handle(message)

    assert outcome.kind is OutcomeKind.ACK
    assert outcome.succeeded
    record = repo.get(message.task_id)
    assert record is not None
    assert record.status is TaskStatus.DONE
    assert record.output == {"confirmation": "AC-1", "echo": message.payload}
    assert [e["event"] for e in record.events] == ["ENQUEUED", "STARTED", "COMPLETED"]
    assert record.duration_seconds is not None


def test_transient_error_schedules_retry_with_policy_delay(make_processor, repo, message):
    outcome = make_processor(ScriptedBot(["transient"])).handle(message)

    assert outcome.kind is OutcomeKind.RETRY
    assert outcome.delay_seconds == 5
    assert repo.get_status(message.task_id) is TaskStatus.RETRYING


def test_unexpected_exception_is_treated_as_transient(make_processor, repo, message):
    outcome = make_processor(ScriptedBot(["crash"])).handle(message)

    assert outcome.kind is OutcomeKind.RETRY
    assert "RuntimeError" in (outcome.error or "")


def test_exhausted_attempts_go_to_dead_letter(make_processor, repo, message):
    processor = make_processor(ScriptedBot(["transient", "transient", "transient"]))
    attempt = message
    kinds = []
    for _ in range(3):
        outcome = processor.handle(attempt)
        kinds.append(outcome.kind)
        attempt = attempt.next_attempt()

    assert kinds == [OutcomeKind.RETRY, OutcomeKind.RETRY, OutcomeKind.DEAD]
    record = repo.get(message.task_id)
    assert record is not None
    assert record.status is TaskStatus.FAILED
    assert record.attempts == 3


def test_second_retry_uses_next_delay(make_processor, message):
    processor = make_processor(ScriptedBot(["transient", "transient"]))
    processor.handle(message)
    outcome = processor.handle(message.next_attempt())
    assert outcome.delay_seconds == 30


def test_business_error_is_not_retried(make_processor, repo, message):
    bot = ScriptedBot(["business"])
    outcome = make_processor(bot).handle(message)

    assert outcome.kind is OutcomeKind.DEAD
    assert len(bot.calls) == 1
    assert repo.get_status(message.task_id) is TaskStatus.FAILED


def test_duplicate_delivery_of_finished_task_is_skipped(make_processor, message):
    bot = ScriptedBot(["ok", "ok"])
    processor = make_processor(bot)
    processor.handle(message)

    outcome = processor.handle(message)  # reentrega de RabbitMQ

    assert outcome.kind is OutcomeKind.ACK
    assert len(bot.calls) == 1


def test_register_pending_reports_new_and_duplicate(repo: TaskRepository, message) -> None:
    assert repo.register_pending(message) is True
    assert repo.register_pending(message) is False


def test_claim_is_refused_for_finished_task(repo: TaskRepository, message) -> None:
    """``mark_running`` es atómico: no reabre una tarea que otra obrera ya terminó."""
    repo.register_pending(message)
    assert repo.mark_running(message, "w1") is True
    repo.mark_done(message.task_id, 1, {"confirmation": "AC-1"})

    assert repo.mark_running(message.next_attempt(), "w2") is False

    record = repo.get(message.task_id)
    assert record is not None
    assert record.status is TaskStatus.DONE
    assert record.worker_id == "w1"
    assert [e["event"] for e in record.events].count("STARTED") == 1


@pytest.mark.parametrize(
    ("status", "age_minutes", "allowed"),
    [
        (TaskStatus.FAILED, 0, True),
        (TaskStatus.PENDING, 1, False),
        (TaskStatus.PENDING, 15, True),
        (TaskStatus.RUNNING, 60, False),
        (TaskStatus.RETRYING, 60, False),
        (TaskStatus.DONE, 60, False),
    ],
)
def test_requeue_rule(status: TaskStatus, age_minutes: int, allowed: bool) -> None:
    now = utcnow()
    updated = now - timedelta(minutes=age_minutes)
    assert requeue_allowed(status, updated, now, timedelta(minutes=15)) is allowed


def test_unknown_process_goes_to_dead_letter(make_processor, repo):
    msg = TaskMessage(process="nonexistent")
    outcome = make_processor(ScriptedBot([])).handle(msg)

    assert outcome.kind is OutcomeKind.DEAD
    assert repo.get_status(msg.task_id) is TaskStatus.FAILED


def test_message_without_prior_registration_is_created(make_processor, repo, message):
    make_processor(ScriptedBot(["ok"])).handle(message)
    assert repo.get_status(message.task_id) is TaskStatus.DONE


def test_bot_is_recreated_after_system_error(repo, message):
    from colmena_rpa.bots.registry import BotRegistry
    from colmena_rpa.messaging.retry import RetryPolicy
    from colmena_rpa.worker.processor import TaskProcessor

    created: list[ScriptedBot] = []

    def factory() -> ScriptedBot:
        bot = ScriptedBot(["transient"] if not created else ["ok"])
        created.append(bot)
        return bot

    registry = BotRegistry()
    registry.register("scripted", factory)
    processor = TaskProcessor(repo, registry, RetryPolicy(3, (5,)), "w")

    processor.handle(message)
    processor.handle(message.next_attempt())

    assert len(created) == 2
    assert created[0].teardowns == 1
