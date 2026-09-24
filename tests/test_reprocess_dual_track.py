"""Reprocessing a dual-track Meeting keeps the host/remote split of its first run."""

from models.job import JobStatus, JobType
from tasks.process_meeting import process_meeting_task
from tasks.reprocess_task import reidentify_task, rediarize_task

from . import task_harness as h


def _processed(monkeypatch, tmp_path, *, dual_track):
    harness = h.install(
        monkeypatch, tmp_path, transcriber=h.FakeTranscriber(h.WORDS), diarization=h.PYANNOTE
    )
    meeting_id = harness.meeting(dual_track=dual_track)
    if dual_track:
        harness.write_dual_tracks(meeting_id)
    job_id = harness.job(meeting_id, JobType.PROCESS_MEETING)
    assert process_meeting_task(meeting_id, job_id)["status"] == "completed"
    harness.diarizer.calls.clear()
    return harness, meeting_id


def _host(meeting):
    return next((s for s in meeting.speakers if s.label == "HOST"), None)


def test_rediarize_runs_the_diarizer_on_the_system_track(monkeypatch, tmp_path):
    harness, meeting_id = _processed(monkeypatch, tmp_path, dual_track=True)

    job_id = harness.job(meeting_id, JobType.REDIARIZE)
    assert rediarize_task(meeting_id, job_id)["status"] == "completed"

    meeting = harness.load(meeting_id)
    assert len(harness.diarizer.calls) == 1
    assert harness.diarizer.calls[0][0].endswith("system_processed.wav")
    assert meeting.raw_diarization["host_label"] == "HOST"
    host = _host(meeting)
    assert host is not None
    assert (host.display_name, host.identified_by) == ("You", "host_track")


def test_reidentify_keeps_the_host_named_you(monkeypatch, tmp_path):
    harness, meeting_id = _processed(monkeypatch, tmp_path, dual_track=True)

    job_id = harness.job(meeting_id, JobType.REIDENTIFY)
    assert reidentify_task(meeting_id, job_id)["status"] == "completed"

    meeting = harness.load(meeting_id)
    assert harness.diarizer.calls == []
    host = _host(meeting)
    assert (host.display_name, host.identified_by) == ("You", "host_track")


def test_rediarize_fails_the_job_when_the_processed_tracks_are_gone(monkeypatch, tmp_path):
    harness, meeting_id = _processed(monkeypatch, tmp_path, dual_track=True)
    (harness.track_dir(meeting_id) / "system_processed.wav").unlink()

    job_id = harness.job(meeting_id, JobType.REDIARIZE)
    try:
        rediarize_task(meeting_id, job_id)
    except RuntimeError:
        pass
    else:
        raise AssertionError("rediarize_task should fail without the system track")

    job = harness.job_row(job_id)
    assert job.status == JobStatus.FAILED
    assert "system_processed.wav" in job.error
    assert harness.diarizer.calls == []


def test_single_track_rediarize_still_diarizes_the_meeting_audio(monkeypatch, tmp_path):
    harness, meeting_id = _processed(monkeypatch, tmp_path, dual_track=False)

    job_id = harness.job(meeting_id, JobType.REDIARIZE)
    assert rediarize_task(meeting_id, job_id)["status"] == "completed"

    meeting = harness.load(meeting_id)
    assert [call[0] for call in harness.diarizer.calls] == [meeting.audio_filepath]
    assert "host_label" not in meeting.raw_diarization
    assert _host(meeting) is None
