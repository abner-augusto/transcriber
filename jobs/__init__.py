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


class NothingToCancel(Exception):
    """The Meeting has no PENDING or RUNNING Job."""


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


def notify_meeting_changed(meeting_id: str) -> None:
    """Tell the Meeting's open pages that its Speakers, Segments or details changed outside a Job."""
    try:
        _progress_adapter().publish(meeting_id, {"type": "meeting_changed"})
    except Exception:
        log.exception("Could not publish a change to Meeting %s", meeting_id)


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


def cancel(db, meeting_id: str) -> Job:
    """Ask the runner to stop the Meeting's PENDING or RUNNING Job; return the Job.

    Only records the request: the runner's loop stops the child and moves the Job to
    CANCELLED a moment later (``cancel_job``). Asking again returns the same Job.
    """
    meeting = db.get(Meeting, meeting_id)
    if meeting is None:
        raise MeetingNotFoundError("Meeting not found")
    job = (
        db.query(Job)
        .filter(Job.meeting_id == meeting_id, Job.status.in_((JobStatus.PENDING, JobStatus.RUNNING)))
        .order_by(Job.created_at.desc())
        .first()
    )
    if job is None:
        raise NothingToCancel("This Meeting has no Job to cancel")
    _runner_adapter().cancel(job.id)
    db.refresh(job)
    if job.cancel_requested_at is None:  # it finished between the lookup and the request
        raise NothingToCancel("The Job finished before it could be cancelled")
    return job


def request_cancel(job_id: str, *, session_factory=None) -> bool:
    """Record that the user wants a PENDING or RUNNING Job stopped, once.

    Returns whether a request was recorded now. Changes no status: the runner's loop,
    and only it, stops the child process and makes the transition (``cancel_job``).
    """
    db = sessions(session_factory)()
    try:
        recorded = db.execute(
            update(Job)
            .where(Job.id == job_id)
            .where(Job.status.in_((JobStatus.PENDING, JobStatus.RUNNING)))
            .where(Job.cancel_requested_at.is_(None))
            .values(cancel_requested_at=datetime.utcnow())
        ).rowcount == 1
        db.commit()
        return recorded
    finally:
        db.close()


def cancel_requested(job_id: str, *, session_factory=None) -> bool:
    """Whether the user asked to stop this Job and it has not finished."""
    db = sessions(session_factory)()
    try:
        job = db.get(Job, job_id)
        return (
            job is not None
            and job.cancel_requested_at is not None
            and job.status in (JobStatus.PENDING, JobStatus.RUNNING)
        )
    finally:
        db.close()


def cancelled_pending(*, exclude: str | None = None, session_factory=None) -> list[str]:
    """Ids of queued PENDING Jobs whose cancellation was requested (never ``exclude``)."""
    db = sessions(session_factory)()
    try:
        query = db.query(Job.id).filter(
            Job.status == JobStatus.PENDING, Job.cancel_requested_at.isnot(None)
        )
        if exclude is not None:
            query = query.filter(Job.id != exclude)
        return [row[0] for row in query.order_by(Job.created_at.asc())]
    finally:
        db.close()


def cancel_job(job_id: str, *, session_factory=None, progress_bus=None) -> bool:
    """Move a PENDING or RUNNING Job to CANCELLED and its Meeting back to where it was.

    Called by the runner's loop once the Job's process (if any) is dead, never while it
    can still write. Returns False, changing nothing, when the Job is missing or already
    finished: a Job that completed first stays COMPLETED.

    The Meeting goes back to COMPLETED when it still holds a transcript (Words and
    Segments), otherwise to UPLOADED. A Job that had started also loses what it made
    (plan 048): the work files, and on a Meeting going back to UPLOADED the partial Words,
    Turns, Segments and Speakers an older run left. The original recording is never touched.
    """
    db = sessions(session_factory)()
    try:
        job = db.get(Job, job_id)
        if job is None or job.status not in (JobStatus.PENDING, JobStatus.RUNNING):
            return False
        started = job.status == JobStatus.RUNNING
        job.status = JobStatus.CANCELLED
        job.current_step = "Cancelled"
        job.completed_at = datetime.utcnow()
        meeting_id = job.meeting_id
        meeting = db.get(Meeting, meeting_id)
        transcribed = False
        if meeting is not None and meeting.status == MeetingStatus.PROCESSING:
            transcribed = _restore_meeting(db, meeting, discard_partial=started)
        db.commit()
        if started and meeting is not None:
            from services.audio_retention import drop_cancelled_work
            drop_cancelled_work(meeting, keep_audio=transcribed)
    finally:
        db.close()
    try:
        (progress_bus or _progress_adapter()).publish(meeting_id, {"type": "cancelled"})
    except Exception:
        log.exception("Could not publish the cancellation of Job %s", job_id)
    return True


def _restore_meeting(db, meeting: Meeting, *, discard_partial: bool) -> bool:
    """Put a PROCESSING Meeting back to COMPLETED or UPLOADED; say whether it is transcribed."""
    from models import Segment, Speaker
    from transcript.words import words_from_stored

    transcribed = bool(words_from_stored(meeting.raw_transcription)) and (
        db.query(Segment.id).filter(Segment.meeting_id == meeting.id).first() is not None
    )
    if transcribed:
        meeting.status = MeetingStatus.COMPLETED
        return True
    meeting.status = MeetingStatus.UPLOADED
    if discard_partial:
        db.query(Segment).filter(Segment.meeting_id == meeting.id).delete()
        db.query(Speaker).filter(Speaker.meeting_id == meeting.id).delete()
        meeting.raw_transcription = None
        meeting.raw_diarization = None
    return False


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
        if job is None or job.status not in (JobStatus.PENDING, JobStatus.RUNNING):
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
