"""Publicación de tareas con *publisher confirms* y mensajes persistentes."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Protocol

import pika

from rpa_orchestrator.domain.models import TaskMessage
from rpa_orchestrator.messaging.topology import ProcessTopology


class Publisher(Protocol):
    """Puerto de publicación: permite inyectar dobles de prueba en el monitor y el productor."""

    def publish(self, message: TaskMessage) -> None: ...


class TaskPublisher:
    def __init__(self, channel: Any, exchange: str, delays_seconds: tuple[int, ...]) -> None:
        self._channel = channel
        self._exchange = exchange
        self._delays = delays_seconds
        self._declared: dict[str, ProcessTopology] = {}
        self._channel.confirm_delivery()

    def topology(self, process: str) -> ProcessTopology:
        topology = self._declared.get(process)
        if topology is None:
            topology = ProcessTopology(self._exchange, process, self._delays)
            topology.declare(self._channel)
            self._declared[process] = topology
        return topology

    def publish(self, message: TaskMessage) -> None:
        self.topology(message.process)
        self._send(self._exchange, message.process, message)

    def publish_retry(self, message: TaskMessage, delay_seconds: int) -> None:
        queue = self.topology(message.process).retry_queue(delay_seconds)
        self._send("", queue, message, headers={"x-retry-delay": delay_seconds})

    def publish_dead(self, message: TaskMessage, error: str) -> None:
        topology = self.topology(message.process)
        self._send(
            topology.dead_letter_exchange,
            message.process,
            message,
            headers={"x-error": error[:1000]},
        )

    def _send(
        self,
        exchange: str,
        routing_key: str,
        message: TaskMessage,
        headers: dict[str, Any] | None = None,
    ) -> None:
        self._channel.basic_publish(
            exchange=exchange,
            routing_key=routing_key,
            body=message.to_bytes(),
            properties=pika.BasicProperties(
                content_type="application/json",
                delivery_mode=pika.DeliveryMode.Persistent,
                message_id=str(message.task_id),
                correlation_id=message.correlation_id,
                headers={"attempt": message.attempt, **(headers or {})},
            ),
            mandatory=True,
        )


@contextmanager
def open_publisher(
    amqp_url: str, exchange: str, delays: tuple[int, ...]
) -> Iterator[TaskPublisher]:
    connection = pika.BlockingConnection(pika.URLParameters(amqp_url))
    try:
        yield TaskPublisher(connection.channel(), exchange, delays)
    finally:
        connection.close()
