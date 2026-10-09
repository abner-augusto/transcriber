"""Review Notes: the model, the Meeting payload, the routes and the JSON export."""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import URL

import database
from main import app
from models import Meeting, MeetingStatus, ReviewNote, Segment, Speaker


def seed(db, *, status=MeetingStatus.COMPLETED):
    meeting = Meeting(title="Obra 12", status=status, duration=60.0)
    db.add(meeting)
    db.flush()
    ana = Speaker(meeting_id=meeting.id, label="SPEAKER_00", display_name="Participant 1")
    bia = Speaker(meeting_id=meeting.id, label="SPEAKER_01", display_name="Participant 2")
    db.add_all([ana, bia])
    db.flush()
    first = Segment(meeting_id=meeting.id, speaker_id=ana.id, order=0, start_time=0.0,
                    end_time=5.0, text="Galo disse isso", original_text="Galo disse isso")
    second = Segment(meeting_id=meeting.id, speaker_id=bia.id, order=1, start_time=10.0,
                     end_time=15.0, text="Concordo", original_text="Concordo")
    db.add_all([first, second])
    db.commit()
    return meeting, ana, bia, first, second


def add_note(db, meeting, **kw):
    fields = dict(start_time=0.0, end_time=5.0, author="agent", kind="comment", body="Olhar aqui")
    fields.update(kw)
    note = ReviewNote(meeting_id=meeting.id, **fields)
    db.add(note)
    db.commit()
    return note


def test_meeting_payload_lists_review_notes(db_session):
    meeting, *_ = seed(db_session)
    add_note(db_session, meeting, start_time=10.0, end_time=15.0, body="depois")
    add_note(db_session, meeting, start_time=0.0, end_time=5.0, body="antes")

    data = TestClient(app).get(f"/api/meetings/{meeting.id}").json()

    assert [n["body"] for n in data["review_notes"]] == ["antes", "depois"]
    note = data["review_notes"][0]
    assert note["status"] == "open"
    assert note["author"] == "agent"
    assert note["kind"] == "comment"
    assert note["meeting_id"] == meeting.id
    assert note["created_at"] is not None
    assert note["resolved_at"] is None
    assert note["payload"] is None


def test_deleting_a_meeting_deletes_its_notes(db_session):
    meeting, *_ = seed(db_session)
    add_note(db_session, meeting)

    db_session.delete(meeting)
    db_session.commit()

    assert db_session.query(ReviewNote).count() == 0


def test_fresh_database_has_review_notes_table(tmp_path, monkeypatch):
    engine = create_engine(
        URL.create("sqlite", database=str(tmp_path / "app.db")),
        connect_args={"check_same_thread": False},
    )
    database.configure_sqlite_engine(engine)
    monkeypatch.setattr(database, "engine", engine)

    database.init_db()

    assert "review_notes" in inspect(engine).get_table_names()
    engine.dispose()


def test_segment_for_range_finds_the_segment_an_exact_range_points_at(db_session):
    from meeting_store import segment_for_range

    meeting, _, _, first, second = seed(db_session)

    assert segment_for_range(db_session, meeting.id, 0.0, 5.0).id == first.id
    assert segment_for_range(db_session, meeting.id, 10.0, 15.0).id == second.id


def test_segment_for_range_tolerates_a_one_second_shift(db_session):
    from meeting_store import segment_for_range

    meeting, _, _, first, _ = seed(db_session)

    assert segment_for_range(db_session, meeting.id, 1.0, 6.0).id == first.id


def test_segment_for_range_is_none_five_seconds_away(db_session):
    from meeting_store import segment_for_range

    meeting, *_ = seed(db_session)

    assert segment_for_range(db_session, meeting.id, 5.0, 10.0) is None


def test_segment_for_range_prefers_the_nearer_neighbour(db_session):
    from meeting_store import segment_for_range

    meeting, ana, _, first, _ = seed(db_session)
    close = Segment(meeting_id=meeting.id, speaker_id=ana.id, order=2, start_time=5.5,
                    end_time=9.0, text="vizinho", original_text="vizinho")
    db_session.add(close)
    db_session.commit()

    assert segment_for_range(db_session, meeting.id, 5.4, 8.9).id == close.id
    assert segment_for_range(db_session, meeting.id, 0.2, 5.1).id == first.id


def test_duplicating_a_meeting_does_not_copy_notes(db_session, monkeypatch, tmp_path):
    audio = tmp_path / "meeting.wav"
    audio.write_bytes(b"RIFF")
    meeting, *_ = seed(db_session)
    meeting.audio_filepath = str(audio)
    add_note(db_session, meeting)
    ready = {"id": "ready", "name": "Ready", "engine": "parakeet.cpp", "model_path": "m"}
    monkeypatch.setattr("api.meetings.presets.resolve_preset", lambda _preset_id: ready)
    monkeypatch.setattr("api.meetings.presets.get_preset", lambda _preset_id: ready)
    monkeypatch.setattr("api.meetings.probe_engine", lambda _preset: type(
        "Ready", (), {"to_dict": lambda self: {"state": "ready", "summary": "ready"}})())
    monkeypatch.setattr("api.meetings._require_usable_diarizer", lambda: {"state": "ready"})
    monkeypatch.setattr("config.settings.storage_path", str(tmp_path / "storage"))

    response = TestClient(app).post(f"/api/meetings/{meeting.id}/duplicate", json={"preset_id": "ready"})

    assert response.status_code == 200
    copy_id = response.json()["id"]
    assert copy_id != meeting.id
    assert db_session.query(ReviewNote).filter(ReviewNote.meeting_id == copy_id).count() == 0
    assert db_session.query(ReviewNote).filter(ReviewNote.meeting_id == meeting.id).count() == 1
