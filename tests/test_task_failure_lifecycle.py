"""A failing Job body leaves its Job and Meeting FAILED and tells subscribers once."""

import pytest

from engines import DiarizationResult, Turn, Word
import jobs
from models import Job, Meeting, MeetingStatus
from models.job import JobStatus, JobType
from tasks.process_meeting import process_meeting_task
from tasks.reprocess_task import rediarize_task, reidentify_task

from . import task_harness as h
from .fakes import FakeTranscriber


class FailingTranscriber(FakeTranscriber):
    def transcribe(self, audio_path, vocabulary=None):
        raise RuntimeError("engine failed")


class RecordingBus:
    def __init__(self):
        self.events = []

    def publish(self, meeting_id, event):
        self.events.append((meeting_id, event))

    async def subscribe(self, meeting_id):
        if False:
            yield {}


def _engine_failed(*args, **kwargs):
    raise RuntimeError("engine failed")


def _install(monkeypatch, tmp_path, transcriber):
    harness = h.install(
        monkeypatch, tmp_path,
        transcriber=transcriber,
        diarization=DiarizationResult(turns=[Turn(0, 1, "SPEAKER_00")]),
    )
    bus = RecordingBus()
    jobs.configure(progress_bus=bus)
    return harness, bus


def _assert_failed_once(harness, meeting_id, job_id, bus):
    with harness.session_factory() as db:
        meeting = db.get(Meeting, meeting_id)
        job = db.get(Job, job_id)
        assert (meeting.status, job.status, job.error) == (
            MeetingStatus.FAILED, JobStatus.FAILED, "engine failed"
        )
        assert job.completed_at is not None
    assert [event for event in bus.events if event[1].get("type") == "error"] == [
        (meeting_id, {"type": "error", "error": "engine failed"})
    ]


def test_processing_failure_propagates_after_persisting_failure(monkeypatch, tmp_path):
    harness, bus = _install(monkeypatch, tmp_path, FailingTranscriber([]))
    meeting_id = harness.meeting()
    job_id = harness.job(meeting_id, JobType.PROCESS_MEETING)

    with pytest.raises(RuntimeError, match="engine failed"):
        process_meeting_task(meeting_id, job_id)

    _assert_failed_once(harness, meeting_id, job_id, bus)


@pytest.mark.parametrize(
    ("task", "job_type", "failing_stage"),
    [
        (rediarize_task, JobType.REDIARIZE, "tests.fakes.FakeDiarizer.diarize"),
        (reidentify_task, JobType.REIDENTIFY,
         "services.speaker_id_service.SpeakerIdService.name_speakers"),
    ],
)
def test_reprocessing_failure_propagates_after_persisting_failure(
    monkeypatch, tmp_path, task, job_type, failing_stage
):
    harness, bus = _install(monkeypatch, tmp_path, FakeTranscriber([Word(0.1, 0.6, " olá")]))
    meeting_id = harness.meeting()
    assert process_meeting_task(meeting_id, harness.job(meeting_id, JobType.PROCESS_MEETING))["status"] == "completed"
    monkeypatch.setattr(failing_stage, _engine_failed)
    job_id = harness.job(meeting_id, job_type)

    with pytest.raises(RuntimeError, match="engine failed"):
        task(meeting_id, job_id)

    _assert_failed_once(harness, meeting_id, job_id, bus)
