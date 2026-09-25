import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
import jobs
from models import Job, Meeting, MeetingStatus
from models.job import JobStatus, JobType


class FailingTranscriber:
    def load(self):
        pass

    def transcribe(self, audio_path, vocabulary=None):
        raise RuntimeError("engine failed")

def _database(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'tasks.db'}")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    jobs.configure(session_factory=session_factory)
    return session_factory


def _install_events(monkeypatch, events):
    class Bus:
        def publish(self, meeting_id, data):
            events.append((meeting_id, data))

        async def subscribe(self, meeting_id):
            if False:
                yield {}
    jobs.configure(progress_bus=Bus())


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
    from .task_harness import TEST_RUN_CONFIG

    session_factory = _database(tmp_path, monkeypatch)
    meeting_id, job_id = _meeting_and_job(session_factory, JobType.PROCESS_MEETING)
    events = []
    _install_events(monkeypatch, events)

    monkeypatch.setattr("run_config.resolve_run_config", lambda meeting: TEST_RUN_CONFIG)
    monkeypatch.setattr("preferences.hf_token", lambda: "")
    monkeypatch.setattr(
        "tasks.process_meeting.make_transcriber", lambda run_config: FailingTranscriber()
    )
    monkeypatch.setattr("tasks.process_meeting.make_diarizer", lambda run_config, **kwargs: object())
    monkeypatch.setattr(
        "services.audio_service.AudioService.extract_audio",
        lambda self, filepath, current_meeting_id: filepath,
    )
    monkeypatch.setattr(
        "services.audio_service.AudioService.get_duration", lambda self, filepath: 1.0
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
    from .task_harness import TEST_RUN_CONFIG

    session_factory = _database(tmp_path, monkeypatch)
    meeting_id, job_id = _meeting_and_job(session_factory, job_type)
    events = []
    _install_events(monkeypatch, events)

    monkeypatch.setattr("run_config.resolve_run_config", lambda meeting: TEST_RUN_CONFIG)
    monkeypatch.setattr("tasks.reprocess_task.hf_token", lambda: "")

    def fail_reprocessing(db, meeting, job, run_config, rerun_diarization):
        raise RuntimeError("engine failed")

    monkeypatch.setattr(reprocess_module, "_reprocess_meeting", fail_reprocessing)

    with pytest.raises(RuntimeError, match="engine failed"):
        getattr(reprocess_module, task_name)(meeting_id, job_id)

    _assert_failed_once(session_factory, meeting_id, job_id, events)


def test_successful_reprocessing_return_and_lifecycle_are_unchanged(
    monkeypatch, tmp_path
):
    import tasks.reprocess_task as reprocess_module
    from .task_harness import TEST_RUN_CONFIG

    session_factory = _database(tmp_path, monkeypatch)
    meeting_id, job_id = _meeting_and_job(session_factory, JobType.REIDENTIFY)
    events = []
    _install_events(monkeypatch, events)

    monkeypatch.setattr("run_config.resolve_run_config", lambda meeting: TEST_RUN_CONFIG)
    monkeypatch.setattr("tasks.reprocess_task.hf_token", lambda: "")

    monkeypatch.setattr(
        reprocess_module,
        "_reprocess_meeting",
        lambda db, meeting, job, run_config, rerun_diarization: None,
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
