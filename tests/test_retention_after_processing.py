"""A finished Job leaves the Meeting folder with the derived audio only."""

import pytest

from models.job import JobType
from tasks.process_meeting import process_meeting_task

from . import task_harness as h
from .fakes import FakeTranscriber


def _folder(harness, meeting_id, *names):
    directory = harness.track_dir(meeting_id)
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / name).write_bytes(b"RIFF")
    return directory


def _names(directory):
    return sorted(p.name for p in directory.iterdir())


def _install(monkeypatch, tmp_path, transcriber=None):
    return h.install(
        monkeypatch, tmp_path,
        transcriber=transcriber or FakeTranscriber(h.WORDS), diarization=h.PYANNOTE,
    )


def test_dual_track_meeting_keeps_only_the_mix(monkeypatch, tmp_path):
    harness = _install(monkeypatch, tmp_path)
    meeting_id = harness.meeting(dual_track=True)
    directory = _folder(
        harness, meeting_id, "mic_source.wav", "system_source.wav", "mic_processed.wav",
        "system_processed.wav", "mixed.wav",
    )
    with harness.session_factory() as db:
        meeting = db.get(h.Meeting, meeting_id)
        meeting.mic_audio_filepath = str(directory / "mic_source.wav")
        meeting.system_audio_filepath = str(directory / "system_source.wav")
        db.commit()

    job_id = harness.job(meeting_id, JobType.PROCESS_MEETING)
    assert process_meeting_task(meeting_id, job_id)["status"] == "completed"

    assert _names(directory) == ["mixed.wav"]
    meeting = harness.load(meeting_id)
    assert meeting.audio_filepath == str(directory / "mixed.wav")
    assert (meeting.mic_audio_filepath, meeting.system_audio_filepath) == (None, None)
    assert meeting.is_dual_track is True
    assert len(meeting.segments) > 0


def test_single_track_meeting_keeps_only_audio(monkeypatch, tmp_path):
    harness = _install(monkeypatch, tmp_path)
    meeting_id = harness.meeting()
    directory = _folder(harness, meeting_id, "original.mov", "audio.wav")
    with harness.session_factory() as db:
        db.get(h.Meeting, meeting_id).audio_filepath = str(directory / "original.mov")
        db.commit()
    # The harness's extract_audio returns its input; the real one writes audio.wav.
    import services.audio_service as audio_service
    monkeypatch.setattr(
        audio_service.AudioService, "extract_audio",
        lambda self, fp, mid, track=None: str(directory / "audio.wav"),
    )

    job_id = harness.job(meeting_id, JobType.PROCESS_MEETING)
    assert process_meeting_task(meeting_id, job_id)["status"] == "completed"

    assert _names(directory) == ["audio.wav"]
    assert harness.load(meeting_id).audio_filepath == str(directory / "audio.wav")


class _FailingTranscriber(FakeTranscriber):
    def transcribe(self, audio_path, vocabulary=None):
        raise RuntimeError("engine failed")


def test_a_failed_job_keeps_the_sources_so_a_retry_can_run(monkeypatch, tmp_path):
    harness = _install(monkeypatch, tmp_path, _FailingTranscriber([]))
    meeting_id = harness.meeting(dual_track=True)
    directory = _folder(harness, meeting_id, "mic_source.wav", "system_source.wav")
    with harness.session_factory() as db:
        meeting = db.get(h.Meeting, meeting_id)
        meeting.mic_audio_filepath = str(directory / "mic_source.wav")
        meeting.system_audio_filepath = str(directory / "system_source.wav")
        db.commit()

    job_id = harness.job(meeting_id, JobType.PROCESS_MEETING)
    with pytest.raises(RuntimeError):
        process_meeting_task(meeting_id, job_id)

    assert _names(directory) == ["mic_source.wav", "system_source.wav"]
    assert harness.load(meeting_id).mic_audio_filepath == str(directory / "mic_source.wav")
