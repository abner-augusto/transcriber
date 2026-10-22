"""A single uploaded file is read for its tracks; the user can overrule the guess."""

import pytest
from fastapi.testclient import TestClient

from main import app
from models import Meeting, MeetingStatus

MIC = {"stream": 1, "channel": None}
SYSTEM = {"stream": 2, "channel": None}
MIX = {"stream": 0, "channel": None}

# OBS with the mix on track 1: the guess is tracks 2 and 3.
OBS_LAYOUT = {
    "tracks": [
        {**MIX, "title": None, "status": "mix", "level_db": -18.0},
        {**MIC, "title": "Mic", "status": "speech", "level_db": -24.0},
        {**SYSTEM, "title": "Desktop", "status": "speech", "level_db": -27.0},
    ],
    "mic": MIC, "system": SYSTEM, "audio": None, "manual": False,
}
# A fake stereo: one track, read from channel 0.
FAKE_STEREO_LAYOUT = {
    "tracks": [
        {"stream": 0, "channel": 0, "title": None, "status": "speech", "level_db": -20.0},
        {"stream": 0, "channel": 1, "title": None, "status": "duplicate", "level_db": -20.0},
    ],
    "mic": None, "system": None, "audio": {"stream": 0, "channel": 0}, "manual": False,
}


@pytest.fixture
def client(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr("config.settings.storage_path", str(tmp_path / "storage"))
    monkeypatch.setattr(
        "api.meetings.AudioService.probe_audio",
        lambda self, path: {"stream_count": 3, "channels": 1, "streams": []},
    )
    analyzed = []

    def analyze(self, path):
        analyzed.append(path)
        return analyze.layout

    analyze.layout = OBS_LAYOUT
    monkeypatch.setattr("api.meetings.AudioService.analyze_tracks", analyze)
    test_client = TestClient(app)
    test_client.analyze = analyze
    test_client.analyzed = analyzed
    return test_client


def _upload(client):
    response = client.post(
        "/api/meetings",
        data={"title": "T"},
        files={"file": ("obs.mkv", b"bytes", "video/x-matroska")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_a_file_with_a_mic_and_a_system_track_is_dual_track_with_the_guessed_layout(client, db_session):
    body = _upload(client)

    meeting = db_session.get(Meeting, body["id"])
    assert meeting.is_dual_track is True
    assert meeting.mic_audio_filepath == meeting.system_audio_filepath
    assert meeting.audio_filepath is None
    assert meeting.track_layout == OBS_LAYOUT
    assert body["track_layout"] == OBS_LAYOUT
    assert client.analyzed == [meeting.mic_audio_filepath]


def test_a_fake_stereo_is_a_single_track_read_from_one_channel(client, db_session):
    client.analyze.layout = FAKE_STEREO_LAYOUT

    body = _upload(client)

    meeting = db_session.get(Meeting, body["id"])
    assert not meeting.is_dual_track
    assert meeting.audio_filepath and meeting.mic_audio_filepath is None
    assert meeting.track_layout["audio"] == {"stream": 0, "channel": 0}


def test_a_plain_mono_file_is_not_analyzed(client, db_session, monkeypatch):
    monkeypatch.setattr(
        "api.meetings.AudioService.probe_audio",
        lambda self, path: {"stream_count": 1, "channels": 1, "streams": []},
    )

    body = _upload(client)

    assert client.analyzed == []
    meeting = db_session.get(Meeting, body["id"])
    assert not meeting.is_dual_track and meeting.track_layout is None
    assert meeting.audio_filepath


def test_a_failed_analysis_does_not_fail_the_upload(client, db_session, monkeypatch):
    def broken(self, path):
        raise RuntimeError("ffmpeg failed")

    monkeypatch.setattr("api.meetings.AudioService.analyze_tracks", broken)

    body = _upload(client)

    meeting = db_session.get(Meeting, body["id"])
    assert not meeting.is_dual_track and meeting.track_layout is None
    assert meeting.audio_filepath


# --- overruling the guess ----------------------------------------------------------------

def _put(client, meeting_id, **body):
    return client.put(f"/api/meetings/{meeting_id}/tracks", json=body)


def test_the_user_can_swap_the_mic_and_the_system(client, db_session):
    meeting_id = _upload(client)["id"]

    response = _put(client, meeting_id, mic=SYSTEM, system=MIC)

    assert response.status_code == 200
    layout = response.json()["track_layout"]
    assert (layout["mic"], layout["system"], layout["manual"]) == (SYSTEM, MIC, True)
    assert layout["tracks"] == OBS_LAYOUT["tracks"]  # what was detected stays visible
    assert db_session.get(Meeting, meeting_id).track_layout == layout


def test_a_dual_track_guess_can_be_made_a_single_file(client, db_session):
    meeting_id = _upload(client)["id"]

    response = _put(client, meeting_id, mic=MIC, system=None)

    assert response.status_code == 200
    meeting = db_session.get(Meeting, meeting_id)
    assert meeting.is_dual_track is False
    assert meeting.mic_audio_filepath is None and meeting.system_audio_filepath is None
    assert meeting.audio_filepath
    assert (meeting.track_layout["mic"], meeting.track_layout["system"]) == (None, None)
    assert meeting.track_layout["audio"] == MIC


def test_a_single_file_guess_can_be_made_dual_track(client, db_session):
    client.analyze.layout = FAKE_STEREO_LAYOUT
    meeting_id = _upload(client)["id"]
    left, right = FAKE_STEREO_LAYOUT["tracks"][0], FAKE_STEREO_LAYOUT["tracks"][1]
    left, right = ({"stream": t["stream"], "channel": t["channel"]} for t in (left, right))

    response = _put(client, meeting_id, mic=left, system=right)

    assert response.status_code == 200
    meeting = db_session.get(Meeting, meeting_id)
    assert meeting.is_dual_track is True
    assert meeting.audio_filepath is None
    assert meeting.mic_audio_filepath == meeting.system_audio_filepath
    assert (meeting.track_layout["mic"], meeting.track_layout["system"]) == (left, right)
    assert meeting.track_layout["audio"] is None


@pytest.mark.parametrize(
    "body, status",
    [
        ({"mic": {"stream": 9, "channel": None}, "system": None}, 400),  # not a track of the file
        ({"mic": MIC, "system": MIC}, 400),  # the same track twice
        ({"mic": None, "system": SYSTEM}, 400),  # a system without a mic
        ({"mic": None, "system": None}, 400),
    ],
)
def test_an_assignment_that_does_not_fit_the_file_is_refused_and_changes_nothing(
    client, db_session, body, status
):
    meeting_id = _upload(client)["id"]

    response = _put(client, meeting_id, **body)

    assert response.status_code == status
    assert db_session.get(Meeting, meeting_id).track_layout == OBS_LAYOUT


def test_a_meeting_that_was_processed_keeps_its_tracks(client, db_session):
    meeting_id = _upload(client)["id"]
    meeting = db_session.get(Meeting, meeting_id)
    meeting.status = MeetingStatus.COMPLETED
    db_session.commit()

    assert _put(client, meeting_id, mic=SYSTEM, system=MIC).status_code == 409


def test_a_meeting_without_a_file_to_choose_from_has_no_tracks_to_set(client, db_session, monkeypatch):
    monkeypatch.setattr(
        "api.meetings.AudioService.probe_audio",
        lambda self, path: {"stream_count": 1, "channels": 1, "streams": []},
    )
    meeting_id = _upload(client)["id"]

    assert _put(client, meeting_id, mic=MIC, system=None).status_code == 409


def test_an_unknown_meeting_is_a_404(client):
    assert _put(client, "nope", mic=MIC, system=None).status_code == 404
