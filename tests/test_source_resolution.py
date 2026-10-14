"""Reruns that need the originals read them where the Source Reference says, or search for them."""

import os

import pytest

import preferences
from models import Job, Meeting, MeetingStatus
from models.job import JobType
from services import source_reference as sources


def _recording(tmp_path, folder, name, fill):
    path = tmp_path / folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(fill * 5000)
    return path


def _dual(db, tmp_path, *, in_folder="project"):
    """A processed dual-track Meeting whose tracks only exist as originals outside the app."""
    mic = _recording(tmp_path, in_folder, "mic.wav", b"m")
    system = _recording(tmp_path, in_folder, "system.wav", b"s")
    meeting = Meeting(
        title="Dual", status=MeetingStatus.COMPLETED, is_dual_track=True,
        audio_filepath=str(tmp_path / "storage" / "x" / "audio.wav"),
        raw_transcription={"words": []}, raw_diarization={"turns": []},
        source_refs={
            "mic": sources.reference(mic, path=str(mic)),
            "system": sources.reference(system, path=str(system)),
        },
    )
    db.add(meeting)
    db.commit()
    return meeting, mic, system


def _post(client, meeting, route):
    if route == "duplicate":
        return client.post(f"/api/meetings/{meeting.id}/duplicate", json={"preset_id": "ready"})
    return client.post(f"/api/meetings/{meeting.id}/{route}")


def test_reprocessable_follows_the_reference_without_hashing_or_searching(db_session, tmp_path):
    meeting, mic, _system = _dual(db_session, tmp_path)
    assert meeting.to_dict()["reprocessable"] is True

    mic.unlink()

    assert meeting.to_dict()["reprocessable"] is False
    assert [s["state"] for s in meeting.to_dict()["sources"]] == ["missing", "present"]


def test_full_reprocess_reads_the_originals_in_place(db_session, ready_engines, tmp_path):
    meeting, mic, system = _dual(db_session, tmp_path)

    response = _post(ready_engines, meeting, "process")

    assert response.status_code == 200
    db_session.refresh(meeting)
    assert (meeting.mic_audio_filepath, meeting.system_audio_filepath) == (str(mic), str(system))
    assert mic.read_bytes() == b"m" * 5000  # read-only
    assert db_session.query(Job).one().job_type == JobType.PROCESS_MEETING


@pytest.mark.parametrize("route", ["process", "rediarize", "duplicate"])
def test_a_stale_path_is_a_409_that_says_how_to_point_it_again(
    db_session, ready_engines, tmp_path, route
):
    meeting, mic, _system = _dual(db_session, tmp_path)
    mic.unlink()

    response = _post(ready_engines, meeting, route)

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "mic.wav was not found" in detail
    assert f"transcriber_cli set {meeting.id} --source NEW_PATH" in detail
    assert db_session.query(Job).count() == 0
    assert db_session.query(Meeting).count() == 1


def test_a_file_with_other_content_at_the_saved_path_is_not_the_recording(
    db_session, ready_engines, tmp_path
):
    meeting, _mic, system = _dual(db_session, tmp_path)
    system.write_bytes(b"x" * 5000)

    response = _post(ready_engines, meeting, "process")

    assert response.status_code == 409
    assert "system.wav was not found" in response.json()["detail"]
    assert "--system-source NEW_PATH" in response.json()["detail"]


def test_search_roots_find_a_moved_original_and_heal_the_reference(
    db_session, ready_engines, tmp_path
):
    meeting, mic, system = _dual(db_session, tmp_path, in_folder="inbox")
    moved = tmp_path / "projects" / "obra 12"
    moved.mkdir(parents=True)
    mic.rename(moved / "Reuniao mic.wav")
    system.rename(moved / "Reuniao sistema.wav")
    preferences.update({"source_roots": [str(tmp_path / "projects")]})

    response = _post(ready_engines, meeting, "process")

    assert response.status_code == 200
    db_session.refresh(meeting)
    assert meeting.mic_audio_filepath == str(moved / "Reuniao mic.wav")
    assert meeting.source_refs["system"]["path"] == str(moved / "Reuniao sistema.wav")
    assert meeting.to_dict()["reprocessable"] is True


def test_a_meeting_with_no_reference_says_to_adopt_one(db_session, ready_engines):
    meeting = Meeting(
        title="Old", status=MeetingStatus.COMPLETED, is_dual_track=True,
        raw_transcription={"words": []},
    )
    db_session.add(meeting)
    db_session.commit()

    response = _post(ready_engines, meeting, "process")

    assert response.status_code == 400
    assert "no longer has its mic and system tracks" in response.json()["detail"]
    assert f"transcriber_cli set {meeting.id} --source PATH --adopt" in response.json()["detail"]


def test_rediarize_needs_only_a_resolvable_original_when_the_tracks_are_gone(
    db_session, ready_engines, tmp_path
):
    meeting, _mic, _system = _dual(db_session, tmp_path)

    response = _post(ready_engines, meeting, "rediarize")

    assert response.status_code == 200
    assert db_session.query(Job).one().job_type == JobType.REDIARIZE


def test_rediarize_keeps_working_from_tracks_the_app_still_holds(db_session, ready_engines, tmp_path):
    meeting, mic, _system = _dual(db_session, tmp_path)
    mic.unlink()  # the original is gone ...
    meeting.source_refs = None
    db_session.commit()
    folder = tmp_path / "storage" / meeting.id
    folder.mkdir(parents=True)
    (folder / "mic_processed.wav").write_bytes(b"RIFF")
    (folder / "system_processed.wav").write_bytes(b"RIFF")

    assert _post(ready_engines, meeting, "rediarize").status_code == 200  # ... the tracks are not


def test_duplicate_points_the_copy_at_the_originals_and_copies_nothing(
    db_session, ready_engines, tmp_path
):
    meeting, mic, system = _dual(db_session, tmp_path)

    response = _post(ready_engines, meeting, "duplicate")

    assert response.status_code == 200
    copy = db_session.get(Meeting, response.json()["id"])
    assert (copy.mic_audio_filepath, copy.system_audio_filepath) == (str(mic), str(system))
    assert copy.source_refs == meeting.source_refs
    assert list((tmp_path / "storage" / copy.id).iterdir()) == []
    assert db_session.query(Job).one().meeting_id == copy.id
    assert os.path.exists(mic)


def test_duplicate_of_a_single_track_meeting_copies_its_reference(db_session, ready_engines, tmp_path):
    audio = _recording(tmp_path, "storage/x", "audio.wav", b"a")
    ref = sources.reference(audio, path="D:/outside/reuniao.wav", name="reuniao.wav")
    meeting = Meeting(
        title="Single", status=MeetingStatus.COMPLETED, audio_filepath=str(audio),
        raw_transcription={"words": []}, source_refs={"audio": ref},
    )
    db_session.add(meeting)
    db_session.commit()

    response = _post(ready_engines, meeting, "duplicate")

    assert response.status_code == 200
    assert db_session.get(Meeting, response.json()["id"]).source_refs == {"audio": ref}
