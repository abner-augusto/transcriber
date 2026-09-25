import asyncio
from datetime import datetime
import os
import threading
import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker

from database import Base, configure_sqlite_engine
from jobs import progress, running
from jobs.runners import InProcessBus, LocalJobRunner
from models import Job, Meeting, MeetingStatus
from models.job import JobStatus, JobType


def _successful_body(meeting_id: str, job_id: str) -> None:
    with running(meeting_id, job_id) as (db, meeting, job):
        progress(db, job, meeting, 25, "Fake stage")


def _raising_body(meeting_id: str, job_id: str) -> None:
    with running(meeting_id, job_id):
        raise RuntimeError("fake child failure")


def _crashing_body(_meeting_id: str, _job_id: str) -> None:
    os._exit(17)


def _sleeping_body(meeting_id: str, job_id: str) -> None:
    with running(meeting_id, job_id):
        time.sleep(5)


def _import_production_bodies_then_complete_body(meeting_id: str, job_id: str) -> None:
    import sys
    from jobs.runners import TASK_HANDLERS, _import_handler

    for path in TASK_HANDLERS.values():
        assert callable(_import_handler(path))
    assert "main" not in sys.modules
    assert "fastapi" not in sys.modules
    _successful_body(meeting_id, job_id)


def _setup(tmp_path, monkeypatch, *, timeout=2):
    database_path = (tmp_path / "runner.db").resolve()
    database_url = URL.create("sqlite", database=str(database_path)).render_as_string(
        hide_password=False
    )
    monkeypatch.setenv("DATABASE_URL", database_url)
    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False},
    )
    configure_sqlite_engine(engine)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    bus = InProcessBus()
    runner = LocalJobRunner(
        progress_bus=bus,
        session_factory=sessions,
        handler_paths={
            JobType.PROCESS_MEETING: f"{__name__}._{timeout}_body",
        },
        poll_interval=0.01,
        minimum_timeout_seconds=0.25 if timeout == "sleeping" else 5,
        duration_multiplier=0,
    )
    return engine, sessions, bus, runner


def _add_job(sessions, title="Runner", created_at=None):
    with sessions() as db:
        meeting = Meeting(
            title=title,
            status=MeetingStatus.PROCESSING,
            preset_id="faster-whisper-large-v3",
        )
        db.add(meeting)
        db.flush()
        job = Job(
            meeting_id=meeting.id,
            job_type=JobType.PROCESS_MEETING,
            status=JobStatus.PENDING,
            created_at=created_at or datetime.utcnow(),
        )
        db.add(job)
        db.commit()
        return meeting.id, job.id


def _wait_for_status(sessions, job_id, status, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with sessions() as db:
            job = db.get(Job, job_id)
            if job and job.status == status:
                return job
        time.sleep(0.02)
    raise AssertionError(f"Job {job_id} did not reach {status.value}")


def _wait_for_final_progress(sessions, job_id, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with sessions() as db:
            job = db.get(Job, job_id)
            if job and job.progress == 100 and job.current_step == "Done!":
                return job
        time.sleep(0.01)
    raise AssertionError(f"Job {job_id} did not relay final progress")


def test_in_process_bus_publishes_from_thread_to_two_subscribers_and_unsubscribes():
    async def scenario():
        bus = InProcessBus()
        first = bus.subscribe("meeting-1")
        second = bus.subscribe("meeting-1")
        first_event = asyncio.create_task(anext(first))
        second_event = asyncio.create_task(anext(second))
        while bus.subscriber_count("meeting-1") != 2:
            await asyncio.sleep(0.005)

        event = {"type": "progress", "progress": 50, "step": "Working", "status": "processing"}
        publisher = threading.Thread(target=bus.publish, args=("meeting-1", event))
        publisher.start()
        publisher.join()

        assert await asyncio.wait_for(first_event, timeout=1) == event
        assert await asyncio.wait_for(second_event, timeout=1) == event
        await first.aclose()
        await second.aclose()
        assert bus.subscriber_count("meeting-1") == 0

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("handler", "expected_status", "error_fragment"),
    [
        ("successful", JobStatus.COMPLETED, None),
        ("raising", JobStatus.FAILED, "fake child failure"),
        ("crashing", JobStatus.FAILED, "exited with code 17"),
        ("sleeping", JobStatus.FAILED, "time limit"),
    ],
)
def test_local_runner_child_lifecycle(tmp_path, monkeypatch, handler, expected_status, error_fragment):
    engine, sessions, _bus, runner = _setup(tmp_path, monkeypatch, timeout=handler)
    meeting_id, job_id = _add_job(sessions)
    try:
        runner.start()
        with sessions() as db:
            runner.submit(db.get(Job, job_id))
        result = _wait_for_status(sessions, job_id, expected_status)
        if error_fragment:
            assert error_fragment in result.error.lower()
        with sessions() as db:
            meeting = db.get(Meeting, meeting_id)
            assert meeting.status == (
                MeetingStatus.COMPLETED
                if expected_status == JobStatus.COMPLETED
                else MeetingStatus.FAILED
            )
            if expected_status == JobStatus.COMPLETED:
                assert db.get(Job, job_id).progress == 100
    finally:
        runner.stop()
        engine.dispose()


def test_local_runner_resumes_pending_jobs_in_creation_order(tmp_path, monkeypatch):
    engine, sessions, _bus, runner = _setup(tmp_path, monkeypatch, timeout="successful")
    first_id = _add_job(sessions, "First", datetime(2026, 1, 1))[1]
    second_id = _add_job(sessions, "Second", datetime(2026, 1, 2))[1]
    try:
        runner.start()
        _wait_for_status(sessions, first_id, JobStatus.COMPLETED)
        _wait_for_status(sessions, second_id, JobStatus.COMPLETED)
        with sessions() as db:
            assert db.get(Job, first_id).started_at <= db.get(Job, second_id).started_at
    finally:
        runner.stop()
        engine.dispose()


def test_spawned_process_imports_production_task_bodies_without_fastapi(tmp_path, monkeypatch):
    engine, sessions, _bus, runner = _setup(
        tmp_path, monkeypatch, timeout="import_production_bodies_then_complete"
    )
    _meeting_id, job_id = _add_job(sessions)
    try:
        runner.start()
        with sessions() as db:
            runner.submit(db.get(Job, job_id))
        _wait_for_status(sessions, job_id, JobStatus.COMPLETED)
    finally:
        runner.stop()
        engine.dispose()


def test_child_progress_is_persisted_and_published_by_parent(tmp_path, monkeypatch):
    engine, sessions, bus, runner = _setup(tmp_path, monkeypatch, timeout="successful")
    meeting_id, job_id = _add_job(sessions)

    async def receive_progress():
        subscription = bus.subscribe(meeting_id)
        pending_event = asyncio.create_task(anext(subscription))
        while bus.subscriber_count(meeting_id) == 0:
            await asyncio.sleep(0.005)
        runner.start()
        with sessions() as db:
            runner.submit(db.get(Job, job_id))
        event = await asyncio.wait_for(pending_event, timeout=5)
        await subscription.aclose()
        return event

    try:
        event = asyncio.run(receive_progress())
        assert event == {
            "type": "progress", "progress": 25, "step": "Fake stage",
            "status": "processing",
        }
        result = _wait_for_status(sessions, job_id, JobStatus.COMPLETED)
        final_progress = _wait_for_final_progress(sessions, job_id)
        assert final_progress.progress == 100
        assert final_progress.current_step == "Done!"
    finally:
        runner.stop()
        engine.dispose()


def test_runner_timeout_uses_sixty_minutes_or_three_times_audio_duration(tmp_path):
    database_path = (tmp_path / "timeout.db").resolve()
    engine = create_engine(URL.create("sqlite", database=str(database_path)))
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    runner = LocalJobRunner(session_factory=sessions)
    with sessions() as db:
        meeting = Meeting(title="Duration", duration=None)
        db.add(meeting)
        db.commit()
        meeting_id = meeting.id

    assert runner._timeout_seconds(meeting_id) == 3600
    with sessions() as db:
        db.get(Meeting, meeting_id).duration = 1300
        db.commit()
    assert runner._timeout_seconds(meeting_id) == 3900
    engine.dispose()


def test_runner_shutdown_interrupts_active_child(tmp_path, monkeypatch):
    engine, sessions, _bus, runner = _setup(tmp_path, monkeypatch, timeout="sleeping")
    runner.minimum_timeout_seconds = 20
    meeting_id, job_id = _add_job(sessions)
    runner.start()
    with sessions() as db:
        runner.submit(db.get(Job, job_id))
    _wait_for_status(sessions, job_id, JobStatus.RUNNING)

    try:
        runner.stop()
        result = _wait_for_status(sessions, job_id, JobStatus.FAILED)
        assert "application shutdown" in result.error.lower()
        with sessions() as db:
            assert db.get(Meeting, meeting_id).status == MeetingStatus.FAILED
    finally:
        runner.stop()
        engine.dispose()
