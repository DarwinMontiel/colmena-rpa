"""Latido del worker: reporta estado y contadores a PostgreSQL para el monitor."""

from __future__ import annotations

import platform
import socket
import threading
from uuid import UUID

from rpa_orchestrator import __version__
from rpa_orchestrator.domain.models import WorkerState, utcnow
from rpa_orchestrator.logging import get_logger
from rpa_orchestrator.persistence.repository import Heartbeat, HeartbeatRepository

log = get_logger(__name__)


class HeartbeatService:
    def __init__(
        self,
        repository: HeartbeatRepository,
        worker_id: str,
        processes: list[str],
        interval_seconds: float,
    ) -> None:
        self._repo = repository
        self._worker_id = worker_id
        self._processes = processes
        self._interval = interval_seconds
        self._lock = threading.Lock()
        self._state = WorkerState.IDLE
        self._current: UUID | None = None
        self._ok = 0
        self._failed = 0
        self._started_at = utcnow()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # --- cambios de estado (llamados desde el hilo de procesamiento) ---
    def busy(self, task_id: UUID) -> None:
        with self._lock:
            self._state, self._current = WorkerState.BUSY, task_id
        self.beat()

    def idle(self, succeeded: bool | None) -> None:
        """``True`` terminada, ``False`` fallida definitiva, ``None`` reintento programado."""
        with self._lock:
            self._state, self._current = WorkerState.IDLE, None
            if succeeded is True:
                self._ok += 1
            elif succeeded is False:
                self._failed += 1
        self.beat()

    def stopping(self) -> None:
        with self._lock:
            self._state = WorkerState.STOPPING
        self.beat()

    def snapshot(self) -> Heartbeat:
        with self._lock:
            return Heartbeat(
                worker_id=self._worker_id,
                hostname=socket.gethostname(),
                platform=f"{platform.system()} {platform.release()}",
                processes=list(self._processes),
                state=self._state,
                current_task_id=self._current,
                tasks_ok=self._ok,
                tasks_failed=self._failed,
                version=__version__,
                started_at=self._started_at,
                last_seen=utcnow(),
            )

    def beat(self) -> None:
        try:
            self._repo.beat(self.snapshot())
        except Exception:
            log.exception("heartbeat.failed")

    # --- ciclo de vida ---
    def start(self) -> None:
        self.beat()
        self._thread = threading.Thread(target=self._loop, name="heartbeat", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self._interval + 1)

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            self.beat()
