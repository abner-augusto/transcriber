import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import Job, Meeting, MeetingStatus
from models.job import JobStatus, JobType


class FailingTranscriber:
    def transcribe(self, audio_path, vocabulary=None):
        raise RuntimeError("engine failed")


def _database(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'tasks.db'}")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    monkeypatch.setattr("tasks.shared.SessionLocal", session_factory)
    return session_factory


def _meeting_and_job(session_factory, job_type):
    with session_factory() as db:
        meeting = Meeting(
            title="Failure lifecycle",
            status=MeetingStatus.UPLOADED,
            audio_filepath="meeting.wav",
        )
        db.add(meeting)
        db.flush()
        job = Job(
            meeting_id=meeting.id,
            job_type=job_type,
            status=JobStatus.PENDING,
        )
        db.add(job)
        db.commit()
        return meeting.id, job.id


def _assert_failed_once(session_factory, meeting_id, job_id, events):
    with session_factory() as db:
        meeting = db.get(Meeting, meeting_id)
        job = db.get(Job, job_id)
        assert meeting.status == MeetingStatus.FAILED
        assert job.status == JobStatus.FAILED
        assert job.error == "engine failed"
        assert job.completed_at is not None

    assert [event for event in events if event[1].get("type") == "error"] == [
        (meeting_id, {"type": "error", "error": "engine failed"})
    ]


def test_processing_failure_propagates_after_persisting_failure(monkeypatch, tmp_path):
    from tasks.process_meeting import process_meeting_task

    session_factory = _database(tmp_path, monkeypatch)
    meeting_id, job_id = _meeting_and_job(session_factory, JobType.PROCESS_MEETING)
    events = []

    monkeypatch.setattr(
        "tasks.process_meeting.resolve_preset",
        lambda preset_id: {"id": "test", "name": "Test", "engine": "test"},
    )
    monkeypatch.setattr(
        "tasks.process_meeting.make_transcriber", lambda preset: FailingTranscriber()
    )
    monkeypatch.setattr("tasks.process_meeting.make_diarizer", lambda: object())
    monkeypatch.setattr(
        "services.audio_service.AudioService.extract_audio",
        lambda self, filepath, current_meeting_id: filepath,
    )
    monkeypatch.setattr(
        "services.audio_service.AudioService.get_duration", lambda self, filepath: 1.0
    )
    monkeypatch.setattr(
        "tasks.shared.publish_event", lambda current_meeting_id, data: events.append((current_meeting_id, data))
    )

    with pytest.raises(RuntimeError, match="engine failed"):
        process_meeting_task(meeting_id, job_id)

    _assert_failed_once(session_factory, meeting_id, job_id, events)


@pytest.mark.parametrize(
    ("task_name", "job_type"),
    [
        ("rediarize_task", JobType.REDIARIZE),
        ("reidentify_task", JobType.REIDENTIFY),
    ],
)
def test_reprocessing_failure_propagates_after_persisting_failure(
    monkeypatch, tmp_path, task_name, job_type
):
    import tasks.reprocess_task as reprocess_module

    session_factory = _database(tmp_path, monkeypatch)
    meeting_id, job_id = _meeting_and_job(session_factory, job_type)
    events = []

    def fail_reprocessing(db, meeting, job, rerun_diarization):
        raise RuntimeError("engine failed")

    monkeypatch.setattr(reprocess_module, "_reprocess_meeting", fail_reprocessing)
    monkeypatch.setattr(
        "tasks.shared.publish_event", lambda current_meeting_id, data: events.append((current_meeting_id, data))
    )

    with pytest.raises(RuntimeError, match="engine failed"):
        getattr(reprocess_module, task_name)(meeting_id, job_id)

    _assert_failed_once(session_factory, meeting_id, job_id, events)


def test_successful_reprocessing_return_and_lifecycle_are_unchanged(
    monkeypatch, tmp_path
):
    import tasks.reprocess_task as reprocess_module

    session_factory = _database(tmp_path, monkeypatch)
    meeting_id, job_id = _meeting_and_job(session_factory, JobType.REIDENTIFY)
    events = []

    monkeypatch.setattr(
        reprocess_module,
        "_reprocess_meeting",
        lambda db, meeting, job, rerun_diarization: None,
    )
    monkeypatch.setattr(
        "tasks.shared.publish_event",
        lambda current_meeting_id, data: events.append((current_meeting_id, data)),
    )

    assert reprocess_module.reidentify_task(meeting_id, job_id) == {
        "status": "completed",
        "meeting_id": meeting_id,
    }

    with session_factory() as db:
        meeting = db.get(Meeting, meeting_id)
        job = db.get(Job, job_id)
        assert meeting.status == MeetingStatus.COMPLETED
        assert job.status == JobStatus.COMPLETED
        assert job.progress == 100
        assert job.completed_at is not None

    assert not [event for event in events if event[1].get("type") == "error"]
