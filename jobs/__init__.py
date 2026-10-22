"""Job lifecycle and its configured runner/progress adapters."""

from contextlib import contextmanager
from datetime import datetime
import logging
from typing import NamedTuple

from sqlalchemy import update

from models import Job, Meeting, MeetingStatus, Segment
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

    previous = (meeting.status, meeting.audio_filepath)  # what a cancel puts the Meeting back to
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
    job = Job(
        meeting_id=meeting.id, job_type=kind, status=JobStatus.PENDING,
        previous_meeting_status=previous[0].value, previous_audio_filepath=previous[1],
    )
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


def cancel_requests(*, session_factory=None) -> dict[str, JobStatus]:
    """The unfinished Jobs the user asked to stop, oldest first: {job id: PENDING or RUNNING}."""
    db = sessions(session_factory)()
    try:
        rows = (
            db.query(Job.id, Job.status)
            .filter(Job.status.in_((JobStatus.PENDING, JobStatus.RUNNING)), Job.cancel_requested_at.isnot(None))
            .order_by(Job.created_at.asc())
        )
        return {job_id: status for job_id, status in rows}
    finally:
        db.close()


def finish_cancel(job_id: str, *, session_factory=None, progress_bus=None) -> bool:
    """Move a PENDING or RUNNING Job to CANCELLED and put its Meeting back where it was.

    Called by the runner's loop once the Job's process (if any) is dead, never while it
    can still write. Returns False, changing nothing, when the Job is missing or already
    finished: a Job whose final transaction was committed first stays COMPLETED.

    The Meeting goes back to the state the Job recorded when it claimed it (``enqueue``):
    COMPLETED stays as it is, untouched; UPLOADED (or FAILED) gets its audio path back. A
    Job that had started also loses the work files it made, and on a Meeting going back to
    UPLOADED the partial Words, Turns, Segments and Speakers. The original recording is
    never touched. A Job made before plan 048 recorded nothing, so its Meeting is put back
    by what it holds (``_was_transcribed``): the fallback.
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
        keep_audio = False
        if meeting is not None and meeting.status == MeetingStatus.PROCESSING:
            keep_audio = _put_back(db, job, meeting, started=started)
        if started and meeting is not None:
            # Before the commit, so that a CANCELLED Job already has its work files gone.
            from services.audio_retention import drop_cancelled_work
            drop_cancelled_work(meeting, keep_audio=keep_audio)
        db.commit()
    finally:
        db.close()
    try:
        (progress_bus or _progress_adapter()).publish(meeting_id, {"type": "cancelled"})
    except Exception:
        log.exception("Could not publish the cancellation of Job %s", job_id)
    return True


def _was_transcribed(db, job: Job, meeting: Meeting) -> bool:
    """Whether the Meeting was COMPLETED when the Job claimed it: what its Reprocessing keeps."""
    if job.previous_meeting_status is not None:
        return job.previous_meeting_status == MeetingStatus.COMPLETED.value
    # Fallback for a Job that recorded nothing: infer it from the data.
    from transcript.words import words_from_stored

    return bool(words_from_stored(meeting.raw_transcription)) and (
        db.query(Segment.id).filter(Segment.meeting_id == meeting.id).first() is not None
    )


def _put_back(db, job: Job, meeting: Meeting, *, started: bool) -> bool:
    """Set the Meeting back to what it was; say whether its audio.wav is still its audio."""
    if _was_transcribed(db, job, meeting):
        meeting.status = MeetingStatus.COMPLETED
        return True
    failed = job.previous_meeting_status == MeetingStatus.FAILED.value
    meeting.status = MeetingStatus.FAILED if failed else MeetingStatus.UPLOADED
    if job.previous_meeting_status is not None:
        meeting.audio_filepath = job.previous_audio_filepath
    if started and not failed:
        from meeting_store import discard_transcript
        discard_transcript(db, meeting)
    return False


class RunningJob(NamedTuple):
    """What a task body works with while ``running`` owns its Job's lifecycle."""

    db: object
    meeting: Meeting
    job: Job
    after_commit_actions: list

    @property
    def run_config(self):
        from run_config import RunConfig
        return RunConfig.model_validate(self.job.run_config)

    @property
    def reprocessing(self) -> bool:
        """Whether the Meeting was COMPLETED when the Job claimed it.

        A Reprocessing keeps the previous transcript whole until its one final
        transaction, so cancelling it (plan 048) leaves the Meeting as it was. A first
        transcription saves each stage as it finishes, so a late failure still leaves
        Words and Turns to Re-diarize or Re-identify from.
        """
        return _was_transcribed(self.db, self.job, self.meeting)

    def progress(self, percent: float, step: str) -> None:
        _progress(self.db, self.job, self.meeting, percent, step)

    def after_commit(self, action) -> None:
        """Run ``action`` once the Job's final transaction is committed (file clean-up).

        A failing action is logged: it never fails a Job that already completed.
        """
        self.after_commit_actions.append(action)


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

        after_commit_actions: list = []
        # The body leaves its results uncommitted: they are saved by this one commit, with
        # the Job's own COMPLETED, so a cancel (which kills the child) finds either all of
        # them or none (plan 048).
        yield RunningJob(db, meeting, job, after_commit_actions)

        meeting.status = MeetingStatus.COMPLETED
        job.status = JobStatus.COMPLETED
        job.progress = 100
        job.current_step = "Done!"
        job.completed_at = datetime.utcnow()
        db.commit()
        for action in after_commit_actions:
            try:
                action()
            except Exception:
                log.exception("A step after the commit of Job %s failed", job_id)
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
