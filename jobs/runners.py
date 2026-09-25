"""Local Job execution and progress adapters."""

from collections.abc import AsyncIterator, Callable, Mapping
from datetime import datetime
import importlib
import logging
import multiprocessing
from multiprocessing.queues import Queue
from queue import Empty
import threading
import time
from typing import Protocol

from models import Job
from models.job import JobType


class JobRunner(Protocol):
    def submit(self, job: Job) -> str | None: ...


class ProgressBus(Protocol):
    def publish(self, meeting_id: str, event: dict) -> None: ...
    def subscribe(self, meeting_id: str) -> AsyncIterator[dict]: ...


TASK_HANDLERS = {
    JobType.PROCESS_MEETING: "tasks.process_meeting.process_meeting_task",
    JobType.REDIARIZE: "tasks.reprocess_task.rediarize_task",
    JobType.REIDENTIFY: "tasks.reprocess_task.reidentify_task",
    JobType.REAPPLY_VOCABULARY: "tasks.reprocess_task.reapply_vocabulary_task",
}

log = logging.getLogger(__name__)


class InlineJobRunner:
    """Run plain task bodies in-process, or record submissions with explicit handlers."""

    def __init__(self, handlers: Mapping[JobType, Callable[[str, str], object]] | None = None):
        self._handlers = handlers
        self.submitted: list[tuple[str, str, JobType]] = []

    def submit(self, job: Job) -> None:
        self.submitted.append((job.meeting_id, job.id, job.job_type))
        handler = (
            self._handlers.get(job.job_type) if self._handlers is not None
            else _import_handler(TASK_HANDLERS[job.job_type])
        )
        if handler is not None:
            handler(job.meeting_id, job.id)
        return None


class InProcessBus:
    """Thread-safe in-process async fan-out for WebSocket subscribers."""

    def __init__(self):
        self._subscribers: dict[str, set[tuple[object, object]]] = {}
        self._lock = threading.RLock()

    def publish(self, meeting_id: str, event: dict) -> None:
        with self._lock:
            subscribers = tuple(self._subscribers.get(meeting_id, ()))
        for loop, queue in subscribers:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, dict(event))
            except RuntimeError:
                self._remove(meeting_id, loop, queue)

    async def subscribe(self, meeting_id: str) -> AsyncIterator[dict]:
        import asyncio

        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        subscriber = (loop, queue)
        with self._lock:
            self._subscribers.setdefault(meeting_id, set()).add(subscriber)
        try:
            while True:
                yield await queue.get()
        finally:
            self._remove(meeting_id, loop, queue)

    def _remove(self, meeting_id: str, loop, queue) -> None:
        with self._lock:
            subscribers = self._subscribers.get(meeting_id)
            if subscribers is None:
                return
            subscribers.discard((loop, queue))
            if not subscribers:
                self._subscribers.pop(meeting_id, None)

    def subscriber_count(self, meeting_id: str) -> int:
        with self._lock:
            return len(self._subscribers.get(meeting_id, ()))


class QueueProgressBus:
    """Child-side publisher; progress persistence and WebSocket fan-out stay in parent."""

    persists_progress_in_parent = True

    def __init__(self, messages: Queue):
        self._messages = messages

    def publish(self, meeting_id: str, event: dict) -> None:
        self._messages.put((meeting_id, dict(event)))

    async def subscribe(self, meeting_id: str) -> AsyncIterator[dict]:
        raise RuntimeError("A Job child cannot subscribe to WebSocket progress")
        yield  # pragma: no cover - makes this an async generator for the protocol


def _stop_process(process) -> None:
    """Terminate a Job child, and kill it if it ignores the request."""
    if not process.is_alive():
        return
    process.terminate()
    process.join(5)
    if process.is_alive():
        process.kill()
        process.join()


def _import_handler(path: str) -> Callable[[str, str], object]:
    module_name, separator, attribute = path.rpartition(".")
    if not separator:
        raise ValueError(f"Job handler must be a dotted module path: {path!r}")
    handler = getattr(importlib.import_module(module_name), attribute)
    if not callable(handler):
        raise TypeError(f"Job handler is not callable: {path!r}")
    return handler


class LocalJobRunner:
    """One worker thread, one spawned child process, and one Job at a time."""

    def __init__(
        self,
        *,
        progress_bus: ProgressBus | None = None,
        session_factory=None,
        handler_paths: Mapping[JobType, str] | None = None,
        poll_interval: float = 0.25,
        minimum_timeout_seconds: float = 3600,
        duration_multiplier: float = 3,
    ):
        self.progress_bus = progress_bus
        self.session_factory = session_factory
        self.handler_paths = dict(handler_paths or TASK_HANDLERS)
        self.poll_interval = poll_interval
        self.minimum_timeout_seconds = minimum_timeout_seconds
        self.duration_multiplier = duration_multiplier
        self._context = multiprocessing.get_context("spawn")
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._active_process = None
        self._active_job_id: str | None = None
        self._active_lock = threading.RLock()

    def submit(self, job: Job) -> None:
        """Wake the durable queue scanner; the Job row is the queue itself."""
        self._wake.set()
        return None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="transcriber-local-job-runner",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 10) -> None:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
        with self._active_lock:
            process = self._active_process
            job_id = self._active_job_id
        if process is not None and process.is_alive():
            _stop_process(process)
            if job_id:
                self._fail_job(job_id, "Job interrupted by application shutdown.")
        self._thread = None

    def _sessions(self):
        from jobs import sessions
        return sessions(self.session_factory)

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                pending = self._oldest_pending()
            except Exception:
                log.exception("Could not inspect the pending Job queue")
                self._wake.wait(self.poll_interval)
                self._wake.clear()
                continue
            if pending is None:
                self._wake.wait(self.poll_interval)
                self._wake.clear()
                continue
            job_id, meeting_id, job_type = pending
            try:
                self._run_job(job_id, meeting_id, job_type)
            except Exception:
                log.exception("Local runner failed while executing Job %s", job_id)
                self._fail_job(job_id, "Local runner failed unexpectedly.")

    def _oldest_pending(self):
        from models import Job
        from models.job import JobStatus

        db = self._sessions()()
        try:
            job = (
                db.query(Job)
                .filter(Job.status == JobStatus.PENDING)
                .order_by(Job.created_at.asc(), Job.id.asc())
                .first()
            )
            if job is None:
                return None
            return job.id, job.meeting_id, job.job_type
        finally:
            db.close()

    def _duration_for_meeting(self, meeting_id: str) -> float | None:
        from models import Meeting

        db = self._sessions()()
        try:
            meeting = db.query(Meeting.duration).filter(Meeting.id == meeting_id).first()
            return float(meeting[0]) if meeting and meeting[0] is not None else None
        finally:
            db.close()

    def _timeout_seconds(self, meeting_id: str) -> float:
        duration = self._duration_for_meeting(meeting_id)
        duration_limit = (duration or 0) * self.duration_multiplier
        return max(self.minimum_timeout_seconds, duration_limit)

    def _run_job(self, job_id: str, meeting_id: str, job_type: JobType) -> None:
        messages = self._context.Queue()
        handler_path = self.handler_paths[job_type]
        process = self._context.Process(
            target=_execute_job_in_child,
            args=(handler_path, meeting_id, job_id, messages),
            name=f"transcriber-job-{job_id[:8]}",
        )
        started = time.monotonic()
        try:
            process.start()
        except Exception as exc:
            messages.close()
            self._fail_job(job_id, f"Could not start Job process: {exc}")
            return

        with self._active_lock:
            self._active_process = process
            self._active_job_id = job_id

        timeout_seconds = self._timeout_seconds(meeting_id)
        deadline = started + timeout_seconds
        next_timeout_check = started + 1
        timed_out = False
        try:
            while process.is_alive():
                if self._stop.is_set():
                    _stop_process(process)
                    self._fail_job(job_id, "Job interrupted by application shutdown.")
                    break

                now = time.monotonic()
                if now >= next_timeout_check:
                    updated_timeout = self._timeout_seconds(meeting_id)
                    if updated_timeout > timeout_seconds:
                        timeout_seconds = updated_timeout
                        deadline = started + timeout_seconds
                    next_timeout_check = now + 1

                if now >= deadline:
                    timed_out = True
                    _stop_process(process)
                    limit_minutes = max(1, round(timeout_seconds / 60))
                    self._fail_job(
                        job_id,
                        f"Job exceeded its {limit_minutes}-minute time limit.",
                    )
                    break

                self._receive_message(messages, timeout=min(0.2, max(0.01, deadline - now)))

            process.join()
            self._drain_messages(messages)
            if not self._stop.is_set() and not timed_out and process.exitcode != 0:
                self._fail_job(
                    job_id,
                    f"Job child process exited with code {process.exitcode}.",
                )
            elif not self._stop.is_set() and not timed_out:
                self._fail_job(job_id, "Job child process exited without completing the Job.")
        finally:
            # Never leave a child on the GPU once this method stops watching it:
            # the loop would otherwise start the next Job next to it.
            _stop_process(process)
            with self._active_lock:
                self._active_process = None
                self._active_job_id = None
            messages.close()
            messages.join_thread()

    def _receive_message(self, messages: Queue, timeout: float) -> None:
        try:
            meeting_id, event = messages.get(timeout=timeout)
        except (Empty, EOFError, OSError):
            return
        self._relay_event(meeting_id, event)

    def _drain_messages(self, messages: Queue) -> None:
        while True:
            try:
                meeting_id, event = messages.get_nowait()
            except (Empty, EOFError, OSError):
                return
            self._relay_event(meeting_id, event)

    def _relay_event(self, meeting_id: str, event: dict) -> None:
        """Relay one progress event. Progress is advisory: a failed relay must
        not stop the Job whose outcome the child records itself."""
        from jobs import relay_event

        try:
            relay_event(meeting_id, event, session_factory=self.session_factory,
                        progress_bus=self.progress_bus)
        except Exception:
            log.exception("Could not relay progress for Meeting %s", meeting_id)

    def _fail_job(self, job_id: str, error: str) -> None:
        from jobs import fail

        fail(job_id, error, session_factory=self.session_factory, progress_bus=self.progress_bus)


def _execute_job_in_child(handler_path: str, meeting_id: str, job_id: str, messages: Queue) -> None:
    from jobs import configure

    configure(progress_bus=QueueProgressBus(messages))
    _import_handler(handler_path)(meeting_id, job_id)