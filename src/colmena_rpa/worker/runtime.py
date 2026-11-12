"""Adaptador RabbitMQ del worker (pika ``BlockingConnection``).

Detalles importantes:

* ``prefetch_count=1``: un bot procesa una tarea a la vez; RabbitMQ reparte la carga entre
  workers (*competing consumers*). Escalar = levantar más workers.
* Las tareas RPA pueden tardar minutos. Si el hilo de la conexión se bloquea, pika deja de
  enviar *heartbeats* AMQP y el broker cierra la conexión. Por eso el bot corre en un hilo
  aparte y el ``ack`` vuelve al hilo de la conexión con ``add_callback_threadsafe``.
* El ``ack`` se envía **después** de persistir el estado y de publicar el reintento o la DLQ:
  semántica *at-least-once*. Los duplicados se neutralizan con la verificación de estado
  final en ``TaskProcessor`` y con la referencia idempotente que envía el bot.
* Si el procesamiento falla por infraestructura (p. ej. PostgreSQL caído), el mensaje se
  devuelve a la cola con ``basic_nack(requeue=True)`` tras una pausa: nunca queda sin
  confirmar ni la obrera queda ocupada para siempre.
* Playwright (API síncrona) exige usarse siempre desde el mismo hilo: el executor tiene un
  único hilo, que crea, usa y cierra los bots.
"""

from __future__ import annotations

import functools
import signal
import time
from concurrent.futures import ThreadPoolExecutor
from types import FrameType
from typing import Any

import pika
from pika.exceptions import AMQPConnectionError
from pydantic import ValidationError

from colmena_rpa.bots.registry import BotRegistry
from colmena_rpa.config import Settings
from colmena_rpa.domain.models import TaskMessage
from colmena_rpa.logging import get_logger
from colmena_rpa.messaging.publisher import TaskPublisher
from colmena_rpa.messaging.topology import ProcessTopology
from colmena_rpa.worker.heartbeat import HeartbeatService
from colmena_rpa.worker.processor import Outcome, OutcomeKind, TaskProcessor

log = get_logger(__name__)


class Worker:
    #: Espera antes de devolver a la cola un mensaje cuyo procesamiento falló por
    #: infraestructura (base de datos, red). Evita reentregas en bucle.
    crash_backoff_seconds: float = 5.0

    def __init__(
        self,
        settings: Settings,
        processor: TaskProcessor,
        registry: BotRegistry,
        heartbeat: HeartbeatService,
    ) -> None:
        self._settings = settings
        self._processor = processor
        self._registry = registry
        self._heartbeat = heartbeat
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bot")
        self._connection: Any = None
        self._channel: Any = None
        self._publisher: TaskPublisher | None = None
        self._running = True

    # ------------------------------------------------------------------ ciclo de vida
    def run_forever(self) -> None:
        self._install_signal_handlers()
        self._heartbeat.start()
        backoff = 1.0
        try:
            while self._running:
                try:
                    self._consume()
                    backoff = 1.0
                except AMQPConnectionError as exc:
                    if not self._running:
                        break
                    log.warning("worker.broker_unavailable", error=str(exc), retry_in=backoff)
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 30)
        finally:
            self._shutdown()

    def stop(self) -> None:
        self._running = False
        self._heartbeat.stopping()
        if self._connection is not None and self._connection.is_open:
            self._connection.add_callback_threadsafe(self._channel.stop_consuming)

    def _consume(self) -> None:
        params = pika.URLParameters(self._settings.amqp_url)
        params.heartbeat = 60
        self._connection = pika.BlockingConnection(params)
        self._channel = self._connection.channel()
        self._channel.basic_qos(prefetch_count=self._settings.prefetch_count)
        delays = tuple(self._settings.retry_delays_seconds)
        self._publisher = TaskPublisher(self._channel, self._settings.exchange, delays)

        for process in self._settings.processes:
            topology = ProcessTopology(self._settings.exchange, process, delays)
            topology.declare(self._channel)
            self._channel.basic_consume(queue=topology.queue, on_message_callback=self._on_message)
            log.info("worker.consuming", queue=topology.queue)

        self._channel.start_consuming()
        # start_consuming retorna tras stop(): dejar terminar la tarea en curso y confirmar.
        self._executor.submit(lambda: None).result()
        self._connection.process_data_events(time_limit=1)
        self._connection.close()

    def _shutdown(self) -> None:
        self._executor.submit(self._registry.close_all).result()
        self._executor.shutdown(wait=True)
        self._heartbeat.stop()
        log.info("worker.stopped")

    def _install_signal_handlers(self) -> None:
        def handler(signum: int, _frame: FrameType | None) -> None:
            log.info("worker.signal_received", signal=signum)
            self.stop()

        signal.signal(signal.SIGINT, handler)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, handler)
        if hasattr(signal, "SIGBREAK"):  # Windows: Ctrl+Break / parada del servicio NSSM
            signal.signal(signal.SIGBREAK, handler)

    # ------------------------------------------------------------------ mensajes
    def _on_message(self, channel: Any, method: Any, _properties: Any, body: bytes) -> None:
        self._executor.submit(self._process, channel, method.delivery_tag, body)

    def _process(self, channel: Any, delivery_tag: int, body: bytes) -> None:
        try:
            message = TaskMessage.from_bytes(body)
        except ValidationError as exc:
            log.error("worker.invalid_message", error=str(exc)[:500])
            self._threadsafe(functools.partial(channel.basic_reject, delivery_tag, requeue=False))
            return

        self._heartbeat.busy(message.task_id)
        try:
            outcome = self._processor.handle(message)
        except Exception:
            # Falla de infraestructura fuera del bot (p. ej. PostgreSQL caído al marcar la
            # tarea). Sin este bloque la excepción quedaría guardada en el Future, el mensaje
            # nunca recibiría ack/nack y, con prefetch=1, la obrera quedaría colgada en BUSY.
            log.exception("worker.processing_crashed", task_id=str(message.task_id))
            self._heartbeat.idle(None)
            # Pausa breve para no entrar en un bucle caliente de reentregas mientras la
            # dependencia se recupera; luego se devuelve el mensaje a la cola.
            time.sleep(self.crash_backoff_seconds)
            self._threadsafe(functools.partial(channel.basic_nack, delivery_tag, requeue=True))
            return
        final = {OutcomeKind.ACK: True, OutcomeKind.DEAD: False}.get(outcome.kind)
        self._heartbeat.idle(final)
        self._threadsafe(functools.partial(self._settle, channel, delivery_tag, message, outcome))

    def _settle(
        self, channel: Any, delivery_tag: int, message: TaskMessage, outcome: Outcome
    ) -> None:
        """Corre en el hilo de la conexión."""
        assert self._publisher is not None
        if outcome.kind is OutcomeKind.RETRY and outcome.delay_seconds is not None:
            self._publisher.publish_retry(message.next_attempt(), outcome.delay_seconds)
        elif outcome.kind is OutcomeKind.DEAD:
            self._publisher.publish_dead(message, outcome.error or "unknown")
        channel.basic_ack(delivery_tag)

    def _threadsafe(self, callback: Any) -> None:
        self._connection.add_callback_threadsafe(callback)
