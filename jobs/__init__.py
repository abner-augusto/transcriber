"""Job lifecycle and its configured runner/progress adapters."""

from contextlib import contextmanager
from datetime import datetime
import logging
from typing import NamedTuple

from sqlalchemy import update

from models import Job, Meeting, MeetingStatus
from models.job import JobStatus, JobType

log = logging.getLogger(__name__)

_runner = None
_progress_bus = None
_session_factory = None
_UNSET = object()


class MeetingNotFoundError(Exception):
    """The requested Meeting or Job does not exist."""


class JobAlreadyRunning(Exception):
    """The atomic Meeting claim failed because another Job is processing it."""


def configure(*, runner=_UNSET, progress_bus=_UNSET, session_factory=_UNSET) -> dict:
    """Select adapters once at startup (or per isolated test fixture).

    Return the previous configuration so a test fixture can restore it afterward.
    """
    global _runner, _progress_bus, _session_factory
    previous = {
        "runner": _runner,
        "progress_bus": _progress_bus,
        "session_factory": _session_factory,
    }
    if runner is not _UNSET:
        _runner = runner
    if progress_bus is not _UNSET:
        _progress_bus = progress_bus
    if session_factory is not _UNSET:
        _session_factory = session_factory
    return previous


def sessions(session_factory=None):
    """The session factory to use: the given one, the configured one, or the app's."""
    if session_factory is not None:
        return session_factory
    if _session_factory is not None:
        return _session_factory
    from database import SessionLocal
    return SessionLocal


def _runner_adapter():
    if _runner is None:
        raise RuntimeError("Job runner has not been configured")
    return _runner


def _progress_adapter():
    if _progress_bus is None:
        raise RuntimeError("Job progress bus has not been configured")
    return _progress_bus


def enqueue(db, meeting_id: str, kind: JobType) -> Job:
    """Atomically claim a Meeting, insert its PENDING Job, and submit it."""
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not meeting:
        raise MeetingNotFoundError("Meeting not found")

    result = db.execute(
        update(Meeting)
        .where(Meeting.id == meeting_id)
        .where(Meeting.status != MeetingStatus.PROCESSING)
        .values(status=MeetingStatus.PROCESSING)
    )
    if result.rowcount == 0:
        db.rollback()
        raise JobAlreadyRunning("Meeting is already being processed")

    meeting.status = MeetingStatus.PROCESSING
    job = Job(meeting_id=meeting.id, job_type=kind, status=JobStatus.PENDING)
    db.add(job)
    db.commit()

    _runner_adapter().submit(job)
    db.refresh(job)
    return job


class RunningJob(NamedTuple):
    """What a task body works with while ``running`` owns its Job's lifecycle."""

    db: object
    meeting: Meeting
    job: Job

    @property
    def run_config(self):
        from run_config import RunConfig
        return RunConfig.model_validate(self.job.run_config)

    def progress(self, percent: float, step: str) -> None:
        _progress(self.db, self.job, self.meeting, percent, step)


@contextmanager
def running(meeting_id: str, job_id: str):
    """Open a session and own the RUNNING → COMPLETED/FAILED lifecycle."""
    db = sessions()()
    try:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        job = db.query(Job).filter(Job.id == job_id).first()
        if not meeting or not job:
            raise MeetingNotFoundError("Meeting or Job not found")

        from run_config import resolve_run_config
        job.run_config = resolve_run_config(meeting.preset_id).model_dump(mode="json", exclude_none=True)
        job.status = JobStatus.RUNNING
        job.started_at = datetime.utcnow()
        meeting.status = MeetingStatus.PROCESSING
        db.commit()

        yield RunningJob(db, meeting, job)

        meeting.status = MeetingStatus.COMPLETED
        job.status = JobStatus.COMPLETED
        job.progress = 100
        job.current_step = "Done!"
        job.completed_at = datetime.utcnow()
        db.commit()
        _progress(db, job, meeting, 100, "Done!")
    except Exception as exc:
        db.rollback()
        db.close()
        fail(job_id, str(exc))
        raise
    finally:
        db.close()


def fail(job_id: str, error: str, *, session_factory=None, progress_bus=None) -> bool:
    """Fail a Job that has not finished, and its Meeting; tell subscribers.

    Returns False, changing nothing, when the Job is missing or already finished.
    """
    db = sessions(session_factory)()
    try:
        job = db.get(Job, job_id)
        if job is None or job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
            return False
        _mark_failed(db, job, error)
        meeting_id = job.meeting_id
        db.commit()
    finally:
        db.close()
    try:
        (progress_bus or _progress_adapter()).publish(meeting_id, {"type": "error", "error": error})
    except Exception:
        log.exception("Could not publish the failure of Job %s", job_id)
    return True


def _mark_failed(db, job: Job, error: str) -> None:
    job.status = JobStatus.FAILED
    job.error = error
    job.completed_at = datetime.utcnow()
    meeting = db.get(Meeting, job.meeting_id)
    if meeting is not None and meeting.status == MeetingStatus.PROCESSING:
        meeting.status = MeetingStatus.FAILED


def _progress(db, job: Job, meeting: Meeting, percent: float, step: str) -> None:
    adapter = _progress_adapter()
    if not getattr(adapter, "persists_progress_in_parent", False):
        job.progress = percent
        job.current_step = step
        db.commit()
    adapter.publish(meeting.id, {
        "type": "progress",
        "progress": percent,
        "step": step,
        "status": meeting.status.value,
    })


def relay_event(meeting_id: str, event: dict, *, session_factory=None, progress_bus=None) -> None:
    """Persist child progress in the parent, then fan it out to subscribers."""
    db = sessions(session_factory)()
    try:
        if event.get("type") == "progress":
            # One conditional UPDATE, not read-modify-write: the child may have
            # finished the Job since this event was queued, and a stale value
            # must not overwrite what the child recorded.
            values = {
                column: event[key]
                for key, column in (("progress", Job.progress), ("step", Job.current_step))
                if key in event
            }
            if values:
                db.query(Job).filter(
                    Job.meeting_id == meeting_id, Job.status == JobStatus.RUNNING
                ).update(values, synchronize_session=False)
                db.commit()
    finally:
        db.close()
    (progress_bus or _progress_adapter()).publish(meeting_id, event)


async def subscribe(meeting_id: str):
    async for event in _progress_adapter().subscribe(meeting_id):
        yield event


def recover() -> None:
    """Fail RUNNING Jobs left behind when the application restarts."""
    db = sessions()()
    try:
        stale_jobs = db.query(Job).filter(Job.status == JobStatus.RUNNING).all()
        for job in stale_jobs:
            _mark_failed(db, job, "Job interrupted by an application restart. Please retry.")
        if stale_jobs:
            db.commit()
            log.info("Recovered %d stale Job(s)", len(stale_jobs))
    finally:
        db.close()
