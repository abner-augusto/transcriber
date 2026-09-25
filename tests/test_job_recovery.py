"""Recovering Jobs a dead worker left behind, and only those.

A Job is RUNNING only while a worker holds it. When the worker starts, nothing can be
holding a RUNNING Job any more, so each one was interrupted. A PENDING Job is still
waiting in the broker for that same worker and must be left alone.
"""

from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
import jobs
from jobs.runners import InMemoryProgressBus
from models import Job, Meeting, MeetingStatus
from models.job import JobStatus, JobType


def _database(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'recovery.db'}")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    jobs.configure(session_factory=session_factory, progress_bus=InMemoryProgressBus())
    return session_factory


def _meeting_with_job(session_factory, meeting_status, job_status):
    with session_factory() as db:
        meeting = Meeting(title="Recovery", status=meeting_status, audio_filepath="meeting.wav")
        db.add(meeting)
        db.flush()
        job = Job(meeting_id=meeting.id, job_type=JobType.PROCESS_MEETING, status=job_status)
        if job_status == JobStatus.COMPLETED:
            job.completed_at = datetime(2026, 9, 1)
        db.add(job)
        db.commit()
        return meeting.id, job.id


def _state(session_factory, meeting_id, job_id):
    with session_factory() as db:
        meeting = db.get(Meeting, meeting_id)
        job = db.get(Job, job_id)
        return meeting.status, job.status, job.error, job.completed_at


def test_running_job_is_failed_and_its_meeting_released(monkeypatch, tmp_path):
    session_factory = _database(tmp_path, monkeypatch)
    meeting_id, job_id = _meeting_with_job(session_factory, MeetingStatus.PROCESSING, JobStatus.RUNNING)

    jobs.recover()

    meeting_status, job_status, error, completed_at = _state(session_factory, meeting_id, job_id)
    assert job_status == JobStatus.FAILED
    assert error
    assert completed_at is not None
    assert meeting_status == MeetingStatus.FAILED


def test_pending_job_is_left_for_the_worker(monkeypatch, tmp_path):
    session_factory = _database(tmp_path, monkeypatch)
    meeting_id, job_id = _meeting_with_job(session_factory, MeetingStatus.PROCESSING, JobStatus.PENDING)

    jobs.recover()

    meeting_status, job_status, error, completed_at = _state(session_factory, meeting_id, job_id)
    assert job_status == JobStatus.PENDING
    assert error is None
    assert completed_at is None
    assert meeting_status == MeetingStatus.PROCESSING


def test_completed_jobs_and_meetings_are_untouched(monkeypatch, tmp_path):
    session_factory = _database(tmp_path, monkeypatch)
    meeting_id, job_id = _meeting_with_job(session_factory, MeetingStatus.COMPLETED, JobStatus.COMPLETED)

    jobs.recover()

    assert _state(session_factory, meeting_id, job_id) == (
        MeetingStatus.COMPLETED, JobStatus.COMPLETED, None, datetime(2026, 9, 1),
    )


def test_each_running_job_is_recovered_independently(monkeypatch, tmp_path):
    session_factory = _database(tmp_path, monkeypatch)
    first = _meeting_with_job(session_factory, MeetingStatus.PROCESSING, JobStatus.RUNNING)
    second = _meeting_with_job(session_factory, MeetingStatus.PROCESSING, JobStatus.RUNNING)

    jobs.recover()

    for meeting_id, job_id in (first, second):
        meeting_status, job_status, _, _ = _state(session_factory, meeting_id, job_id)
        assert (meeting_status, job_status) == (MeetingStatus.FAILED, JobStatus.FAILED)


def test_fastapi_startup_does_not_recover_jobs():
    text = (Path(__file__).resolve().parent.parent / "main.py").read_text(encoding="utf-8")
    assert "jobs.recover" not in text


def test_worker_ready_signal_runs_recovery(monkeypatch):
    from celery.signals import worker_ready

    from tasks.celery_app import celery_app  # noqa: F401 (registers bodies and connects handler)
    from jobs.runners import TASK_NAMES

    assert set(TASK_NAMES.values()).issubset(celery_app.tasks)

    calls = []
    monkeypatch.setattr("jobs.recover", lambda: calls.append(True))

    worker_ready.send(sender=None)

    assert calls == [True]
