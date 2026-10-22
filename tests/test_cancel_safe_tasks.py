"""A Job writes its results only at the end, so stopping it leaves the Meeting as it was (plan 048).

The runner stops a cancelled Job by killing its child process, which runs no cleanup. A
kill is simulated here with a BaseException: ``running()`` catches only Exception, so the
Job is left RUNNING and nothing after the raising stage runs, exactly like a dead process.
"""

import pytest

from engines import DiarizationResult, Turn, Word
from models import Segment
from models.job import JobType
from tasks.process_meeting import process_meeting_task
from tasks.reprocess_task import rediarize_task

from . import task_harness as h
from .fakes import FakeDiarizer, FakeTranscriber

OLD_WORDS = [
    Word(start=0.1, end=0.6, text=" antes"),
    Word(start=1.2, end=1.8, text=" do"),
    Word(start=3.2, end=3.8, text=" corte"),
]
NEW_WORDS = [
    Word(start=0.1, end=0.6, text=" depois"),
    Word(start=1.2, end=1.8, text=" do"),
    Word(start=3.2, end=3.8, text=" cancelamento"),
]
OLD_TURNS = DiarizationResult(turns=[Turn(0.0, 4.0, "SPEAKER_00")], exclusive_turns=[Turn(0.0, 4.0, "SPEAKER_00")])
NEW_TURNS = DiarizationResult(
    turns=[Turn(0.0, 2.0, "SPEAKER_05"), Turn(2.0, 4.0, "SPEAKER_06")],
    exclusive_turns=[Turn(0.0, 2.0, "SPEAKER_05"), Turn(2.0, 4.0, "SPEAKER_06")],
)


class Killed(BaseException):
    """The child process was killed here."""


def _completed(monkeypatch, tmp_path):
    harness = h.install(
        monkeypatch, tmp_path, transcriber=FakeTranscriber(OLD_WORDS), diarization=OLD_TURNS
    )
    meeting_id = harness.meeting()
    job_id = harness.job(meeting_id, JobType.PROCESS_MEETING)
    assert process_meeting_task(meeting_id, job_id)["status"] == "completed"
    return harness, meeting_id


def _stored(harness, meeting_id):
    """Everything a Reprocessing could change, read back with a fresh session."""
    with harness.session_factory() as db:
        meeting = db.get(h.Meeting, meeting_id)
        return {
            "audio": meeting.audio_filepath,
            "words": meeting.raw_transcription,
            "turns": meeting.raw_diarization,
            "segments": [
                (s.start_time, s.end_time, s.text, s.speaker.label)
                for s in db.query(Segment).filter(Segment.meeting_id == meeting_id).order_by(Segment.order)
            ],
        }


def _kill_at(monkeypatch, target: str):
    def kill(*args, **kwargs):
        raise Killed

    monkeypatch.setattr(target, kill)


@pytest.mark.parametrize(
    "stage",
    [
        "tests.fakes.FakeDiarizer.diarize",
        "services.speaker_id_service.SpeakerIdService.name_speakers",
        "meeting_store._write_segments",
    ],
)
def test_full_reprocess_killed_midway_leaves_the_previous_transcript_whole(monkeypatch, tmp_path, stage):
    harness, meeting_id = _completed(monkeypatch, tmp_path)
    before = _stored(harness, meeting_id)
    assert before["segments"], "the first run must have produced a transcript to protect"

    monkeypatch.setattr("tasks.process_meeting.make_transcriber", lambda run_config: FakeTranscriber(NEW_WORDS))
    monkeypatch.setattr(
        "tasks.process_meeting.make_diarizer", lambda run_config, **kwargs: FakeDiarizer(NEW_TURNS)
    )
    _kill_at(monkeypatch, stage)
    job_id = harness.job(meeting_id, JobType.PROCESS_MEETING)

    with pytest.raises(Killed):
        process_meeting_task(meeting_id, job_id)

    assert _stored(harness, meeting_id) == before


def test_full_reprocess_that_finishes_replaces_everything_together(monkeypatch, tmp_path):
    harness, meeting_id = _completed(monkeypatch, tmp_path)
    monkeypatch.setattr("tasks.process_meeting.make_transcriber", lambda run_config: FakeTranscriber(NEW_WORDS))
    monkeypatch.setattr(
        "tasks.process_meeting.make_diarizer", lambda run_config, **kwargs: FakeDiarizer(NEW_TURNS)
    )

    job_id = harness.job(meeting_id, JobType.PROCESS_MEETING)
    assert process_meeting_task(meeting_id, job_id)["status"] == "completed"

    after = _stored(harness, meeting_id)
    assert [segment[2] for segment in after["segments"]] == ["depois do", "cancelamento"]
    assert [word["text"] for word in after["words"]["words"]] == [" depois", " do", " cancelamento"]
    assert {turn["speaker"] for turn in after["turns"]["turns"]} == {"SPEAKER_05", "SPEAKER_06"}


@pytest.mark.parametrize(
    "stage",
    [
        "services.speaker_id_service.SpeakerIdService.name_speakers",
        "meeting_store._write_segments",
    ],
)
def test_rediarize_killed_midway_keeps_the_previous_turns_and_segments(monkeypatch, tmp_path, stage):
    harness, meeting_id = _completed(monkeypatch, tmp_path)
    before = _stored(harness, meeting_id)
    monkeypatch.setattr("tasks.reprocess_task.make_diarizer", lambda run_config, **kwargs: FakeDiarizer(NEW_TURNS))
    _kill_at(monkeypatch, stage)
    job_id = harness.job(meeting_id, JobType.REDIARIZE)

    with pytest.raises(Killed):
        rediarize_task(meeting_id, job_id)

    assert _stored(harness, meeting_id) == before
