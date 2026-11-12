"""Topología RabbitMQ por proceso.

Por cada proceso (p. ej. ``payment_agreement``) se declaran:

- ``rpa.<proceso>``                cola principal (quorum, durable) enlazada a ``rpa.tasks``.
- ``rpa.<proceso>.retry.<N>s``      una cola de espera por cada delay, con TTL fijo. Al expirar,
                                     el mensaje vuelve al exchange principal (dead-letter).
- ``rpa.<proceso>.dlq``            cola de mensajes muertos para revisión manual / reproceso.

Se usan colas de retry con TTL fijo (y no TTL por mensaje) para evitar el bloqueo
"head-of-line" de RabbitMQ: en una misma cola todos los mensajes expiran en orden.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

DLX_SUFFIX = ".dlx"


class ChannelLike(Protocol):
    def exchange_declare(self, exchange: str, exchange_type: str, durable: bool) -> Any: ...

    def queue_declare(self, queue: str, durable: bool, arguments: dict[str, Any]) -> Any: ...

    def queue_bind(self, queue: str, exchange: str, routing_key: str) -> Any: ...


@dataclass(frozen=True, slots=True)
class ProcessTopology:
    exchange: str
    process: str
    delays_seconds: tuple[int, ...]

    @property
    def dead_letter_exchange(self) -> str:
        return f"{self.exchange}{DLX_SUFFIX}"

    @property
    def queue(self) -> str:
        return f"rpa.{self.process}"

    @property
    def dead_letter_queue(self) -> str:
        return f"rpa.{self.process}.dlq"

    def retry_queue(self, delay_seconds: int) -> str:
        if delay_seconds not in self.delays_seconds:
            raise ValueError(f"delay {delay_seconds}s no está configurado para {self.process}")
        return f"rpa.{self.process}.retry.{delay_seconds}s"

    def declare(self, channel: ChannelLike) -> None:
        channel.exchange_declare(exchange=self.exchange, exchange_type="direct", durable=True)
        channel.exchange_declare(
            exchange=self.dead_letter_exchange, exchange_type="direct", durable=True
        )

        channel.queue_declare(
            queue=self.queue,
            durable=True,
            arguments={
                "x-queue-type": "quorum",
                # Mensajes rechazados (p. ej. JSON inválido) terminan en la DLQ.
                "x-dead-letter-exchange": self.dead_letter_exchange,
                "x-dead-letter-routing-key": self.process,
            },
        )
        channel.queue_bind(queue=self.queue, exchange=self.exchange, routing_key=self.process)

        channel.queue_declare(
            queue=self.dead_letter_queue, durable=True, arguments={"x-queue-type": "quorum"}
        )
        channel.queue_bind(
            queue=self.dead_letter_queue,
            exchange=self.dead_letter_exchange,
            routing_key=self.process,
        )

        for delay in self.delays_seconds:
            channel.queue_declare(
                queue=self.retry_queue(delay),
                durable=True,
                arguments={
                    "x-message-ttl": delay * 1000,
                    "x-dead-letter-exchange": self.exchange,
                    "x-dead-letter-routing-key": self.process,
                },
            )
