"""Re-pointing a Meeting at the place its original recording moved to."""

import pytest
from fastapi.testclient import TestClient

from main import app
from models import Meeting, MeetingStatus
from services import source_reference as sources


@pytest.fixture
def client(db_session):
    return TestClient(app)


def _recording(tmp_path, folder, name, fill=b"a"):
    path = tmp_path / folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(fill * 5000)
    return path


def _meeting(db, refs, **columns):
    meeting = Meeting(title="Moved", status=MeetingStatus.COMPLETED, source_refs=refs, **columns)
    db.add(meeting)
    db.commit()
    return meeting


def _put(client, meeting, **body):
    return client.put(f"/api/meetings/{meeting.id}/sources", json=body)


def test_repointing_to_the_same_recording_updates_the_path(client, db_session, tmp_path):
    inbox = _recording(tmp_path, "inbox", "mic.wav")
    ref = sources.reference(inbox, path=str(inbox))
    meeting = _meeting(db_session, {"audio": ref})
    moved = tmp_path / "project" / "reuniao.wav"
    moved.parent.mkdir()
    inbox.rename(moved)

    response = _put(client, meeting, source=str(moved))

    assert response.status_code == 200
    db_session.refresh(meeting)
    assert meeting.source_refs["audio"]["path"] == str(moved)
    assert meeting.source_refs["audio"]["hash"] == ref["hash"]
    assert response.json()["sources"][0]["state"] == "present"
    assert moved.exists()  # read-only: the original stays where the user put it


def test_a_different_recording_is_refused_and_nothing_changes(client, db_session, tmp_path):
    inbox = _recording(tmp_path, "inbox", "mic.wav")
    ref = sources.reference(inbox, path=str(inbox))
    meeting = _meeting(db_session, {"audio": ref})
    other = _recording(tmp_path, "project", "other.wav", fill=b"b")

    response = _put(client, meeting, source=str(other))

    assert response.status_code == 409
    assert "is not the same recording as mic.wav" in response.json()["detail"]
    db_session.refresh(meeting)
    assert meeting.source_refs["audio"]["path"] == str(inbox)


def test_each_track_of_a_dual_track_meeting_is_pointed_on_its_own(client, db_session, tmp_path):
    mic = _recording(tmp_path, "inbox", "mic.wav", fill=b"m")
    system = _recording(tmp_path, "inbox", "system.wav", fill=b"s")
    meeting = _meeting(db_session, {
        "mic": sources.reference(mic, path=str(mic)),
        "system": sources.reference(system, path=str(system)),
    }, is_dual_track=True)
    new_system = tmp_path / "project" / "system.wav"
    new_system.parent.mkdir()
    system.rename(new_system)

    assert _put(client, meeting, system_source=str(new_system)).status_code == 200
    db_session.refresh(meeting)
    assert meeting.source_refs["system"]["path"] == str(new_system)
    assert meeting.source_refs["mic"]["path"] == str(mic)

    # The mic file is not the system recording.
    assert _put(client, meeting, system_source=str(mic)).status_code == 409


def test_a_system_source_on_a_single_file_meeting_is_refused(client, db_session, tmp_path):
    file = _recording(tmp_path, "inbox", "mic.wav")
    meeting = _meeting(db_session, {"audio": sources.reference(file)})

    response = _put(client, meeting, source=str(file), system_source=str(file))

    assert response.status_code == 400
    assert "one source file" in response.json()["detail"]


@pytest.mark.parametrize("body", [{}, {"source": "relative/mic.wav"}])
def test_a_missing_or_relative_path_is_a_400(client, db_session, tmp_path, body):
    file = _recording(tmp_path, "inbox", "mic.wav")
    meeting = _meeting(db_session, {"audio": sources.reference(file)})

    assert _put(client, meeting, **body).status_code == 400


def test_a_path_that_is_not_a_file_is_a_400(client, db_session, tmp_path):
    file = _recording(tmp_path, "inbox", "mic.wav")
    meeting = _meeting(db_session, {"audio": sources.reference(file)})

    response = _put(client, meeting, source=str(tmp_path / "absent.wav"))

    assert response.status_code == 400
    assert "not a file" in response.json()["detail"]


def test_a_meeting_without_a_reference_needs_adopt(client, db_session, tmp_path):
    file = _recording(tmp_path, "project", "mic.wav")
    meeting = _meeting(db_session, None, duration=100.0)

    response = _put(client, meeting, source=str(file))

    assert response.status_code == 400
    assert "adopt" in response.json()["detail"]
    db_session.refresh(meeting)
    assert meeting.source_refs is None


def test_adopt_accepts_a_file_of_the_meetings_duration(client, db_session, tmp_path, monkeypatch):
    monkeypatch.setattr("api.meetings.AudioService.get_duration", lambda self, path: 101.0)
    file = _recording(tmp_path, "project", "mic.wav")
    meeting = _meeting(db_session, None, duration=100.0, is_dual_track=True)

    response = _put(client, meeting, source=str(file), adopt=True)

    assert response.status_code == 200
    db_session.refresh(meeting)
    assert meeting.source_refs["audio"]["path"] == str(file)
    assert meeting.source_refs["audio"]["size"] == 5000


def test_adopt_takes_two_tracks_for_a_dual_track_meeting(client, db_session, tmp_path, monkeypatch):
    monkeypatch.setattr("api.meetings.AudioService.get_duration", lambda self, path: 100.0)
    mic = _recording(tmp_path, "project", "mic.wav", fill=b"m")
    system = _recording(tmp_path, "project", "system.wav", fill=b"s")
    meeting = _meeting(db_session, None, duration=100.0, is_dual_track=True)

    assert _put(client, meeting, source=str(mic), system_source=str(system), adopt=True).status_code == 200
    db_session.refresh(meeting)
    assert set(meeting.source_refs) == {"mic", "system"}


def test_adopt_refuses_a_file_of_another_duration(client, db_session, tmp_path, monkeypatch):
    monkeypatch.setattr("api.meetings.AudioService.get_duration", lambda self, path: 400.0)
    file = _recording(tmp_path, "project", "mic.wav")
    meeting = _meeting(db_session, None, duration=100.0)

    response = _put(client, meeting, source=str(file), adopt=True)

    assert response.status_code == 409
    assert "duration" in response.json()["detail"]
    db_session.refresh(meeting)
    assert meeting.source_refs is None


def test_adopt_needs_the_mic_file_when_it_gets_a_system_file(client, db_session, tmp_path):
    system = _recording(tmp_path, "project", "system.wav", fill=b"s")
    meeting = _meeting(db_session, None, is_dual_track=True)

    response = _put(client, meeting, system_source=str(system), adopt=True)

    assert response.status_code == 400
    assert "both source" in response.json()["detail"]
