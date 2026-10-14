"""Routes that re-run a Meeting from audio answer clearly when the app no longer holds it."""

import os

import pytest
from fastapi.testclient import TestClient

from main import app
from models import Job, Meeting, MeetingStatus
from models.job import JobType

READY = {"id": "ready", "name": "Ready", "engine": "parakeet.cpp", "model_path": "m"}


@pytest.fixture
def ready_engines(monkeypatch, tmp_path):
    monkeypatch.setattr("config.settings.storage_path", str(tmp_path / "storage"))
    monkeypatch.setattr("api.meetings.presets.resolve_preset", lambda _id: READY)
    monkeypatch.setattr("api.meetings.presets.get_preset", lambda _id: READY)
    monkeypatch.setattr("api.meetings.probe_engine", lambda _preset: type(
        "Ready", (), {"to_dict": lambda self: {"state": "ready", "summary": "ready"}})())
    monkeypatch.setattr("api.meetings._require_usable_diarizer", lambda: {"state": "ready"})
    return TestClient(app)


def _add(db_session, **columns) -> Meeting:
    columns.setdefault("raw_transcription", {"words": []})
    meeting = Meeting(title="Audio", status=MeetingStatus.COMPLETED, **columns)
    db_session.add(meeting)
    db_session.commit()
    return meeting


def _file(directory, name):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(b"RIFF" + name.encode())
    return str(path)


def _post(client, meeting, route):
    if route == "duplicate":
        return client.post(f"/api/meetings/{meeting.id}/duplicate", json={"preset_id": "ready"})
    return client.post(f"/api/meetings/{meeting.id}/{route}")


def test_reprocessable_follows_what_the_app_still_holds(db_session):
    single = _add(db_session, audio_filepath="audio.wav")
    kept = _add(db_session, is_dual_track=True, mic_audio_filepath="m.wav", system_audio_filepath="s.wav")
    dropped = _add(db_session, is_dual_track=True, audio_filepath="audio.wav")

    assert single.to_dict()["reprocessable"] is True
    assert kept.to_dict()["reprocessable"] is True
    assert dropped.to_dict()["reprocessable"] is False


@pytest.mark.parametrize("route", ["process", "rediarize", "duplicate"])
def test_dual_track_meeting_without_its_tracks_is_refused_with_a_reason(
    db_session, ready_engines, route
):
    meeting = _add(db_session, is_dual_track=True, audio_filepath="storage/x/audio.wav")

    response = _post(ready_engines, meeting, route)

    assert response.status_code == 400
    assert "no longer has its mic and system tracks" in response.json()["detail"]
    assert db_session.query(Job).count() == 0
    assert db_session.query(Meeting).count() == 1
    meeting_status = db_session.get(Meeting, meeting.id).status
    assert meeting_status == MeetingStatus.COMPLETED


def test_duplicate_shares_the_sources_instead_of_copying_them(db_session, ready_engines, tmp_path):
    source_dir = tmp_path / "storage" / "source"
    mic = _file(source_dir, "mic_source.wav")
    system = _file(source_dir, "system_source.wav")
    meeting = _add(
        db_session, is_dual_track=True, mic_audio_filepath=mic, system_audio_filepath=system
    )

    response = _post(ready_engines, meeting, "duplicate")

    assert response.status_code == 200
    copy = db_session.get(Meeting, response.json()["id"])
    assert copy.is_dual_track is True
    assert os.path.samefile(copy.mic_audio_filepath, mic)
    assert os.path.samefile(copy.system_audio_filepath, system)
    assert copy.mic_audio_filepath != mic
    assert [(job.meeting_id, job.job_type) for job in db_session.query(Job)] == [
        (copy.id, JobType.PROCESS_MEETING)
    ]
    # Deleting the source Meeting's file leaves the copy readable.
    os.unlink(mic)
    assert open(copy.mic_audio_filepath, "rb").read() == b"RIFFmic_source.wav"


def test_duplicate_falls_back_to_a_copy_where_links_are_impossible(
    db_session, ready_engines, tmp_path, monkeypatch
):
    def no_links(src, dst):
        raise OSError("cross-device link")

    monkeypatch.setattr("os.link", no_links)
    audio = _file(tmp_path / "storage" / "source", "audio.wav")
    meeting = _add(db_session, audio_filepath=audio)

    response = _post(ready_engines, meeting, "duplicate")

    assert response.status_code == 200
    copy = db_session.get(Meeting, response.json()["id"])
    assert open(copy.audio_filepath, "rb").read() == b"RIFFaudio.wav"
    assert not os.path.samefile(copy.audio_filepath, audio)


def test_single_track_duplicate_shares_the_kept_audio(db_session, ready_engines, tmp_path):
    audio = _file(tmp_path / "storage" / "source", "audio.wav")
    meeting = _add(db_session, audio_filepath=audio)

    response = _post(ready_engines, meeting, "duplicate")

    assert response.status_code == 200
    copy = db_session.get(Meeting, response.json()["id"])
    assert os.path.samefile(copy.audio_filepath, audio)


@pytest.mark.parametrize("dual_track", [False, True])
def test_duplicate_of_a_meeting_whose_file_is_gone_is_a_400_not_a_crash(
    db_session, ready_engines, tmp_path, dual_track
):
    gone = str(tmp_path / "storage" / "source" / "gone.wav")
    columns = (
        {"is_dual_track": True, "mic_audio_filepath": gone, "system_audio_filepath": gone}
        if dual_track else {"audio_filepath": gone}
    )
    meeting = _add(db_session, **columns)

    response = _post(ready_engines, meeting, "duplicate")

    assert response.status_code == 400
    assert "audio file is missing" in response.json()["detail"]
    assert db_session.query(Meeting).count() == 1
    assert db_session.query(Job).count() == 0


def test_a_stereo_original_stays_one_file_in_the_copy(db_session, ready_engines, tmp_path):
    # The pipeline splits a shared file into channels only when both paths are the same file.
    original = _file(tmp_path / "storage" / "source", "original.mov")
    meeting = _add(
        db_session, is_dual_track=True, mic_audio_filepath=original, system_audio_filepath=original
    )

    response = _post(ready_engines, meeting, "duplicate")

    assert response.status_code == 200
    copy = db_session.get(Meeting, response.json()["id"])
    assert copy.mic_audio_filepath == copy.system_audio_filepath
    assert os.path.samefile(copy.mic_audio_filepath, original)
