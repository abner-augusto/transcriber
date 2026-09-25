"""Job lifecycle and its configured runner/progress adapters."""

from contextlib import contextmanager
from datetime import datetime
import logging

from sqlalchemy import update

from models import Job, Meeting, MeetingStatus
from models.job import JobStatus, JobType

log = logging.getLogger(__name__)

_runner = None
_progress_bus = None
_session_factory = None
_soft_time_limit_errors: tuple[type[BaseException], ...] = ()
_UNSET = object()


class MeetingNotFoundError(Exception):
    """The requested Meeting or Job does not exist."""


class JobAlreadyRunning(Exception):
    """The atomic Meeting claim failed because another Job is processing it."""


def configure(
    *, runner=_UNSET, progress_bus=_UNSET, session_factory=_UNSET,
    soft_time_limit_errors=_UNSET,
) -> dict:
    """Select adapters once at startup (or per isolated test fixture).

    Return the previous configuration so a test fixture can restore it afterward.
    """
    global _runner, _progress_bus, _session_factory, _soft_time_limit_errors
    previous = {
        "runner": _runner,
        "progress_bus": _progress_bus,
        "session_factory": _session_factory,
        "soft_time_limit_errors": _soft_time_limit_errors,
    }
    if runner is not _UNSET:
        _runner = runner
    if progress_bus is not _UNSET:
        _progress_bus = progress_bus
    if session_factory is not _UNSET:
        _session_factory = session_factory
    if soft_time_limit_errors is not _UNSET:
        _soft_time_limit_errors = tuple(soft_time_limit_errors)
    return previous


def _sessions():
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


@contextmanager
def running(meeting_id: str, job_id: str):
    """Open a session and own the RUNNING → COMPLETED/FAILED lifecycle."""
    db = _sessions()()
    try:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        job = db.query(Job).filter(Job.id == job_id).first()
        if not meeting or not job:
            raise MeetingNotFoundError("Meeting or Job not found")

        from run_config import resolve_run_config
        job.run_config = resolve_run_config(meeting).model_dump(mode="json", exclude_none=True)
        job.status = JobStatus.RUNNING
        job.started_at = datetime.utcnow()
        meeting.status = MeetingStatus.PROCESSING
        db.commit()

        yield db, meeting, job

        meeting.status = MeetingStatus.COMPLETED
        job.status = JobStatus.COMPLETED
        job.progress = 100
        job.current_step = "Done!"
        job.completed_at = datetime.utcnow()
        db.commit()
        progress(db, job, meeting, 100, "Done!")
    except Exception as exc:
        db.rollback()
        if _soft_time_limit_errors and isinstance(exc, _soft_time_limit_errors):
            error = "Task exceeded time limit (55 minutes). Try a shorter recording."
        else:
            error = str(exc)
        _fail_job(db, meeting_id, job_id, error)
        raise
    finally:
        db.close()


def _fail_job(db, meeting_id: str, job_id: str, error_msg: str) -> None:
    job = db.query(Job).filter(Job.id == job_id).first()
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if job:
        job.status = JobStatus.FAILED
        job.error = error_msg
        job.completed_at = datetime.utcnow()
    if meeting:
        meeting.status = MeetingStatus.FAILED
    db.commit()
    try:
        _progress_adapter().publish(meeting_id, {"type": "error", "error": error_msg})
    except Exception:
        pass


def progress(db, job: Job, meeting: Meeting, percent: float, step: str) -> None:
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
    factory = session_factory or _sessions()
    db = factory()
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


def check_progress_bus() -> None:
    """Check the configured progress transport, if it exposes a health check."""
    check = getattr(_progress_adapter(), "check", None)
    if check is not None:
        check()


async def subscribe(meeting_id: str):
    async for event in _progress_adapter().subscribe(meeting_id):
        yield event


def recover() -> None:
    """Fail RUNNING Jobs left behind when the application restarts."""
    db = _sessions()()
    try:
        stale_jobs = db.query(Job).filter(Job.status == JobStatus.RUNNING).all()
        for job in stale_jobs:
            job.status = JobStatus.FAILED
            job.error = "Job interrupted by worker restart. Please retry."
            job.completed_at = datetime.utcnow()
            meeting = db.query(Meeting).filter(Meeting.id == job.meeting_id).first()
            if meeting and meeting.status == MeetingStatus.PROCESSING:
                meeting.status = MeetingStatus.FAILED
        if stale_jobs:
            db.commit()
            log.info("Recovered %d stale Job(s)", len(stale_jobs))
    finally:
        db.close()
