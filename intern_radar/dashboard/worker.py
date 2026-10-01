"""Slow web actions (letters, CVs, Telegram sends) run in the background.

One thread runs the tasks one at a time, like the Telegram listener: the
services (LLM backend, PDF rendering, Telegram delivery) are built lazily in
that thread, with their own store connection, so a page never waits on them.
Task states live in memory: they only drive the "en cours" banner.
"""

import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

PENDING, RUNNING, DONE, FAILED = "pending", "running", "done", "failed"
KINDS = ("letter", "cv", "telegram")


@dataclass(frozen=True)
class Services:
    """What the background tasks call, keyed by job id or offer ref."""

    letter: Callable[[str], Path | None]
    promote: Callable[[int], bool]
    resume: Callable[[str], Path | None] | None = None


@dataclass(frozen=True)
class TaskState:
    state: str
    error: str = ""


class Worker:
    def __init__(self, build: Callable[[], Services]) -> None:
        self._build = build
        self._services: Services | None = None
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="web-task")
        self._lock = threading.Lock()
        self._states: dict[tuple[str, int], TaskState] = {}

    def submit(self, kind: str, ref: int, job_id: str) -> bool:
        """Queue a task; False when the same one is already queued or running."""
        if kind not in KINDS:
            raise ValueError(kind)
        key = (kind, ref)
        with self._lock:
            current = self._states.get(key)
            if current and current.state in (PENDING, RUNNING):
                return False
            self._states[key] = TaskState(PENDING)
        self._pool.submit(self._run, kind, ref, job_id)
        return True

    def state(self, kind: str, ref: int) -> TaskState | None:
        with self._lock:
            return self._states.get((kind, ref))

    def busy(self, ref: int) -> bool:
        return any(
            (s := self.state(kind, ref)) is not None and s.state in (PENDING, RUNNING)
            for kind in KINDS
        )

    def wait(self) -> None:
        """Block until queued tasks are done (tests)."""
        self._pool.submit(lambda: None).result()

    def _set(self, kind: str, ref: int, state: TaskState) -> None:
        with self._lock:
            self._states[(kind, ref)] = state

    def _run(self, kind: str, ref: int, job_id: str) -> None:
        self._set(kind, ref, TaskState(RUNNING))
        try:
            if self._services is None:
                self._services = self._build()
            ok = self._call(self._services, kind, ref, job_id)
            error = "" if ok else "échec (détail envoyé sur Telegram)"
        except Exception as exc:
            log.exception("web task %s for %s failed", kind, job_id)
            ok, error = False, str(exc) or type(exc).__name__
        self._set(kind, ref, TaskState(DONE) if ok else TaskState(FAILED, error[:300]))

    @staticmethod
    def _call(services: Services, kind: str, ref: int, job_id: str) -> bool:
        if kind == "letter":
            return services.letter(job_id) is not None
        if kind == "cv":
            if services.resume is None:
                raise RuntimeError("CV adapté non configuré (candidate.json)")
            return services.resume(job_id) is not None
        return services.promote(ref)
