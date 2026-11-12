from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from colmena_rpa.domain.models import TaskMessage
from colmena_rpa.messaging.publisher import TaskPublisher
from colmena_rpa.messaging.retry import RetryPolicy
from colmena_rpa.messaging.topology import ProcessTopology


class FakeChannel:
    def __init__(self) -> None:
        self.exchanges: dict[str, str] = {}
        self.queues: dict[str, dict[str, Any]] = {}
        self.bindings: list[tuple[str, str, str]] = []
        self.published: list[dict[str, Any]] = []
        self.confirms = False

    def exchange_declare(self, exchange: str, exchange_type: str, durable: bool) -> None:
        self.exchanges[exchange] = exchange_type

    def queue_declare(self, queue: str, durable: bool, arguments: dict[str, Any]) -> None:
        self.queues[queue] = arguments

    def queue_bind(self, queue: str, exchange: str, routing_key: str) -> None:
        self.bindings.append((queue, exchange, routing_key))

    def confirm_delivery(self) -> None:
        self.confirms = True

    def basic_publish(self, **kwargs: Any) -> None:
        self.published.append(kwargs)


class TestRetryPolicy:
    def test_should_retry_until_max_attempts(self) -> None:
        policy = RetryPolicy(max_attempts=3, delays_seconds=(10, 60))
        assert [policy.should_retry(a) for a in (1, 2, 3)] == [True, True, False]

    def test_delay_caps_at_last_value(self) -> None:
        policy = RetryPolicy(max_attempts=10, delays_seconds=(10, 60, 300))
        assert [policy.delay_for(a) for a in (1, 2, 3, 4, 9)] == [10, 60, 300, 300, 300]

    @pytest.mark.parametrize(("attempts", "delays"), [(0, (1,)), (3, ())])
    def test_invalid_configuration_is_rejected(
        self, attempts: int, delays: tuple[int, ...]
    ) -> None:
        with pytest.raises(ValueError, match=r"max_attempts|delay"):
            RetryPolicy(attempts, delays)


class TestTaskMessage:
    def test_roundtrip_bytes(self) -> None:
        msg = TaskMessage(process="payment_agreement", payload={"a": 1}, correlation_id="lote-1")
        assert TaskMessage.from_bytes(msg.to_bytes()) == msg

    def test_next_attempt_keeps_identity(self) -> None:
        msg = TaskMessage(process="payment_agreement")
        nxt = msg.next_attempt()
        assert (nxt.task_id, nxt.attempt) == (msg.task_id, 2)

    @pytest.mark.parametrize("process", ["", "Payment", "1bot", "a-b"])
    def test_rejects_invalid_process_names(self, process: str) -> None:
        with pytest.raises(ValidationError):
            TaskMessage(process=process)


class TestTopology:
    def test_declares_main_retry_and_dead_letter_queues(self) -> None:
        channel = FakeChannel()
        topo = ProcessTopology("rpa.tasks", "payment_agreement", (10, 60))
        topo.declare(channel)

        assert set(channel.queues) == {
            "rpa.payment_agreement",
            "rpa.payment_agreement.dlq",
            "rpa.payment_agreement.retry.10s",
            "rpa.payment_agreement.retry.60s",
        }
        retry = channel.queues["rpa.payment_agreement.retry.60s"]
        assert retry["x-message-ttl"] == 60_000
        assert retry["x-dead-letter-exchange"] == "rpa.tasks"
        assert retry["x-dead-letter-routing-key"] == "payment_agreement"
        assert channel.queues["rpa.payment_agreement"]["x-queue-type"] == "quorum"
        assert ("rpa.payment_agreement", "rpa.tasks", "payment_agreement") in channel.bindings

    def test_unknown_delay_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="no está configurado"):
            ProcessTopology("x", "p", (10,)).retry_queue(99)


class TestPublisher:
    def test_publish_routes_by_process_with_persistent_messages(self) -> None:
        channel = FakeChannel()
        publisher = TaskPublisher(channel, "rpa.tasks", (10,))
        msg = TaskMessage(process="payment_agreement")

        publisher.publish(msg)

        assert channel.confirms
        sent = channel.published[-1]
        assert (sent["exchange"], sent["routing_key"]) == ("rpa.tasks", "payment_agreement")
        assert sent["properties"].delivery_mode == 2
        assert UUID(sent["properties"].message_id) == msg.task_id
        assert sent["mandatory"] is True

    def test_retry_goes_to_delay_queue_and_dead_to_dlx(self) -> None:
        channel = FakeChannel()
        publisher = TaskPublisher(channel, "rpa.tasks", (10,))
        msg = TaskMessage(process="payment_agreement")

        publisher.publish_retry(msg.next_attempt(), 10)
        publisher.publish_dead(msg, "boom")

        retry, dead = channel.published[-2:]
        assert (retry["exchange"], retry["routing_key"]) == ("", "rpa.payment_agreement.retry.10s")
        assert retry["properties"].headers["attempt"] == 2
        assert dead["exchange"] == "rpa.tasks.dlx"
        assert dead["properties"].headers["x-error"] == "boom"

    def test_topology_is_declared_once_per_process(self) -> None:
        channel = FakeChannel()
        publisher = TaskPublisher(channel, "rpa.tasks", (10,))
        publisher.publish(TaskMessage(process="a"))
        count = len(channel.bindings)
        publisher.publish(TaskMessage(process="a"))
        assert len(channel.bindings) == count
