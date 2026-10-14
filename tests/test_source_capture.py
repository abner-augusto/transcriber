"""Uploading a Meeting records a Source Reference to each original recording."""

import pytest
from fastapi.testclient import TestClient

from main import app
from models import Meeting


@pytest.fixture
def client(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr("config.settings.storage_path", str(tmp_path / "storage"))
    monkeypatch.setattr(
        "api.meetings.AudioService.probe_audio",
        lambda self, path: {"stream_count": 1, "channels": 1, "streams": []},
    )
    return TestClient(app)


def _upload(client, **fields):
    files = {"file": ("reuniao.wav", b"mic-bytes", "audio/wav")}
    if "system" in fields:
        files["system_file"] = ("sistema.wav", fields.pop("system"), "audio/wav")
    return client.post("/api/meetings", data={"title": "T", **fields}, files=files)


def test_a_browser_upload_records_name_size_and_hash_without_a_path(client, db_session):
    response = _upload(client)

    assert response.status_code == 200
    meeting = db_session.get(Meeting, response.json()["id"])
    assert meeting.source_refs == {"audio": {
        "path": None, "name": "reuniao.wav", "size": 9,
        "hash": meeting.source_refs["audio"]["hash"],
    }}
    assert len(meeting.source_refs["audio"]["hash"]) == 64


def test_the_cli_path_is_stored_as_the_place_the_original_lives(client, db_session, tmp_path):
    original = str(tmp_path / "inbox" / "reuniao.wav")

    response = _upload(client, source_path=original)

    meeting = db_session.get(Meeting, response.json()["id"])
    assert meeting.source_refs["audio"]["path"] == original


def test_dual_track_uploads_get_one_reference_per_track(client, db_session, tmp_path):
    response = _upload(
        client, system=b"system-bytes",
        source_path=str(tmp_path / "m.wav"), system_source_path=str(tmp_path / "s.wav"),
    )

    meeting = db_session.get(Meeting, response.json()["id"])
    assert set(meeting.source_refs) == {"mic", "system"}
    assert meeting.source_refs["system"]["name"] == "sistema.wav"
    assert meeting.source_refs["system"]["size"] == 12
    assert meeting.source_refs["system"]["path"] == str(tmp_path / "s.wav")


def test_a_stereo_original_is_one_reference_for_both_tracks(client, db_session, monkeypatch):
    monkeypatch.setattr(
        "api.meetings.AudioService.probe_audio",
        lambda self, path: {"stream_count": 1, "channels": 2, "streams": []},
    )

    response = _upload(client)

    meeting = db_session.get(Meeting, response.json()["id"])
    assert meeting.is_dual_track is True
    assert set(meeting.source_refs) == {"audio"}


def test_a_relative_path_is_refused_and_nothing_is_created(client, db_session):
    response = _upload(client, source_path="inbox/reuniao.wav")

    assert response.status_code == 400
    assert "absolute" in response.json()["detail"]
    assert db_session.query(Meeting).count() == 0
