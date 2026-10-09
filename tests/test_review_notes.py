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


def post_note(client, meeting, **kw):
    body = {"start_time": 0.0, "end_time": 5.0, "kind": "comment", "body": "Olhar aqui", "author": "agent"}
    body.update(kw)
    return client.post(f"/api/meetings/{meeting.id}/notes", json=body)


def test_creating_a_comment_stores_an_open_note(db_session):
    meeting, *_ = seed(db_session)

    response = post_note(TestClient(app), meeting)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "open"
    assert data["kind"] == "comment"
    assert data["author"] == "agent"
    assert data["body"] == "Olhar aqui"
    stored = db_session.query(ReviewNote).one()
    assert stored.id == data["id"]
    assert stored.meeting_id == meeting.id


def test_creating_a_note_in_a_missing_meeting_is_404(db_session):
    seed(db_session)
    response = TestClient(app).post("/api/meetings/nope/notes", json={
        "start_time": 0, "end_time": 1, "kind": "comment", "body": "x", "author": "agent"})
    assert response.status_code == 404


def test_a_note_range_must_not_run_backwards(db_session):
    meeting, *_ = seed(db_session)
    response = post_note(TestClient(app), meeting, start_time=5.0, end_time=1.0)
    assert response.status_code == 400


def test_an_unknown_kind_or_author_is_refused(db_session):
    meeting, *_ = seed(db_session)
    client = TestClient(app)
    assert post_note(client, meeting, kind="shout").status_code == 400
    assert post_note(client, meeting, author="system").status_code == 400
    assert post_note(client, meeting, author="robot").status_code == 400
    assert db_session.query(ReviewNote).count() == 0


def test_a_user_note_must_be_a_comment(db_session):
    meeting, *_ = seed(db_session)
    client = TestClient(app)

    refused = post_note(client, meeting, author="user", kind="question")

    assert refused.status_code == 400
    assert refused.json()["detail"] == "a user note is a comment"
    assert post_note(client, meeting, author="user", kind="comment").status_code == 200


def test_a_blank_body_is_refused(db_session):
    meeting, *_ = seed(db_session)
    assert post_note(TestClient(app), meeting, body="   ").status_code == 400


def test_a_comment_or_question_takes_no_payload(db_session):
    meeting, *_ = seed(db_session)
    client = TestClient(app)
    assert post_note(client, meeting, kind="comment", payload={"x": 1}).status_code == 400
    assert post_note(client, meeting, kind="question", payload={"x": 1}).status_code == 400
    assert post_note(client, meeting, kind="question").status_code == 200


def test_a_text_note_needs_the_current_text_of_a_segment_at_the_range(db_session):
    meeting, *_ = seed(db_session)
    client = TestClient(app)
    good = {"expected_text": "Galo disse isso", "proposed_text": "Garrah disse isso"}

    assert post_note(client, meeting, kind="text", payload=good).status_code == 200
    assert post_note(client, meeting, kind="text", payload=None).status_code == 400
    assert post_note(client, meeting, kind="text", payload={"proposed_text": "x"}).status_code == 400
    stale = {"expected_text": "outro texto", "proposed_text": "x"}
    assert post_note(client, meeting, kind="text", payload=stale).status_code == 400
    elsewhere = post_note(client, meeting, kind="text", payload=good, start_time=40.0, end_time=45.0)
    assert elsewhere.status_code == 400
    assert elsewhere.json()["detail"] == "no Segment at this range"


def test_a_speaker_name_note_needs_a_label_of_the_meeting(db_session):
    meeting, *_ = seed(db_session)
    client = TestClient(app)

    ok = post_note(client, meeting, kind="speaker_name", payload={"label": "SPEAKER_00", "name": "Ana"})
    missing = post_note(client, meeting, kind="speaker_name", payload={"label": "SPEAKER_09", "name": "Ana"})
    incomplete = post_note(client, meeting, kind="speaker_name", payload={"label": "SPEAKER_00"})

    assert ok.status_code == 200
    assert missing.status_code == 400
    assert incomplete.status_code == 400


def test_a_speaker_move_note_needs_a_target_or_a_new_name_and_a_segment(db_session):
    meeting, *_ = seed(db_session)
    client = TestClient(app)

    assert post_note(client, meeting, kind="speaker_move", payload={"target_label": "SPEAKER_01"}).status_code == 200
    assert post_note(client, meeting, kind="speaker_move", payload={"new_name": "Carla"}).status_code == 200
    assert post_note(client, meeting, kind="speaker_move", payload={}).status_code == 400
    assert post_note(client, meeting, kind="speaker_move", payload={"target_label": "SPEAKER_09"}).status_code == 400
    away = post_note(client, meeting, kind="speaker_move", payload={"new_name": "Carla"},
                     start_time=40.0, end_time=45.0)
    assert away.status_code == 400


def test_a_speaker_merge_note_needs_two_different_existing_labels(db_session):
    meeting, *_ = seed(db_session)
    client = TestClient(app)

    ok = post_note(client, meeting, kind="speaker_merge",
                   payload={"source_label": "SPEAKER_00", "target_label": "SPEAKER_01"})
    same = post_note(client, meeting, kind="speaker_merge",
                     payload={"source_label": "SPEAKER_00", "target_label": "SPEAKER_00"})
    missing = post_note(client, meeting, kind="speaker_merge",
                        payload={"source_label": "SPEAKER_00", "target_label": "SPEAKER_09"})

    assert ok.status_code == 200
    assert same.status_code == 400
    assert missing.status_code == 400


def test_creating_a_note_is_allowed_while_the_meeting_is_processing(db_session):
    meeting, *_ = seed(db_session, status=MeetingStatus.PROCESSING)
    assert post_note(TestClient(app), meeting).status_code == 200


def test_creating_a_note_tells_the_meeting_page(db_session, monkeypatch):
    import jobs

    meeting, *_ = seed(db_session)
    seen = []
    monkeypatch.setattr(jobs, "notify_meeting_changed", lambda meeting_id: seen.append(meeting_id))

    post_note(TestClient(app), meeting)

    assert seen == [meeting.id]


def test_listing_notes_filters_by_status_and_orders_by_start(db_session):
    meeting, *_ = seed(db_session)
    add_note(db_session, meeting, start_time=10.0, end_time=12.0, body="late")
    add_note(db_session, meeting, start_time=1.0, end_time=2.0, body="early")
    add_note(db_session, meeting, start_time=3.0, end_time=4.0, body="asked", kind="question", status="answered")
    add_note(db_session, meeting, start_time=5.0, end_time=6.0, body="shelved", status="dismissed")
    add_note(db_session, meeting, start_time=7.0, end_time=8.0, body="finished", status="done")
    add_note(db_session, meeting, start_time=9.0, end_time=9.5, body="taken", kind="text", status="accepted")
    client = TestClient(app)

    def bodies(query=""):
        response = client.get(f"/api/meetings/{meeting.id}/notes{query}")
        assert response.status_code == 200
        return [n["body"] for n in response.json()]

    assert bodies() == ["early", "asked", "shelved", "finished", "taken", "late"]
    assert bodies("?status=all") == bodies()
    assert bodies("?status=open") == ["early", "late"]
    assert bodies("?status=answered") == ["asked"]
    assert bodies("?status=resolved") == ["shelved", "finished", "taken"]
    assert client.get(f"/api/meetings/{meeting.id}/notes?status=weird").status_code == 400
    assert client.get("/api/meetings/nope/notes").status_code == 404


def test_the_user_answers_an_open_question(db_session):
    meeting, *_ = seed(db_session)
    note = add_note(db_session, meeting, kind="question", body="Quem fala?")
    client = TestClient(app)

    response = client.post(f"/api/notes/{note.id}/answer", json={"answer": "A Ana"})

    assert response.status_code == 200
    assert response.json()["status"] == "answered"
    assert response.json()["answer"] == "A Ana"
    db_session.refresh(note)
    assert note.status == "answered"
    assert note.answer == "A Ana"
    assert note.resolved_at is None
    again = client.post(f"/api/notes/{note.id}/answer", json={"answer": "outra"})
    assert again.status_code == 409


def test_only_a_question_can_be_answered(db_session):
    meeting, *_ = seed(db_session)
    note = add_note(db_session, meeting, kind="comment")
    client = TestClient(app)

    assert client.post(f"/api/notes/{note.id}/answer", json={"answer": "x"}).status_code == 409
    assert client.post("/api/notes/nope/answer", json={"answer": "x"}).status_code == 404


def test_an_answered_question_is_closed_with_a_reply(db_session):
    meeting, *_ = seed(db_session)
    note = add_note(db_session, meeting, kind="question", status="answered", answer="A Ana")
    client = TestClient(app)

    response = client.post(f"/api/notes/{note.id}/done", json={"reply": "Renomeei"})

    assert response.status_code == 200
    db_session.refresh(note)
    assert note.status == "done"
    assert note.reply == "Renomeei"
    assert note.resolved_at is not None


def test_an_open_comment_is_closed_with_done_and_an_optional_reply(db_session):
    meeting, *_ = seed(db_session)
    note = add_note(db_session, meeting, kind="comment", author="user")
    client = TestClient(app)

    response = client.post(f"/api/notes/{note.id}/done")

    assert response.status_code == 200
    db_session.refresh(note)
    assert note.status == "done"
    assert note.reply is None
    assert client.post(f"/api/notes/{note.id}/done").status_code == 409


def test_done_refuses_an_open_question_and_a_suggestion(db_session):
    meeting, *_ = seed(db_session)
    question = add_note(db_session, meeting, kind="question")
    suggestion = add_note(db_session, meeting, kind="text",
                          payload={"expected_text": "Galo disse isso", "proposed_text": "x"})
    client = TestClient(app)

    assert client.post(f"/api/notes/{question.id}/done").status_code == 409
    assert client.post(f"/api/notes/{suggestion.id}/done").status_code == 409
    assert client.post("/api/notes/nope/done").status_code == 404


def test_dismiss_closes_a_suggestion_or_a_question_but_not_a_comment(db_session):
    meeting, *_ = seed(db_session)
    suggestion = add_note(db_session, meeting, kind="speaker_name",
                          payload={"label": "SPEAKER_00", "name": "Ana"})
    open_question = add_note(db_session, meeting, kind="question")
    answered = add_note(db_session, meeting, kind="question", status="answered", answer="x")
    comment = add_note(db_session, meeting, kind="comment")
    client = TestClient(app)

    for note in (suggestion, open_question, answered):
        assert client.post(f"/api/notes/{note.id}/dismiss").status_code == 200
        db_session.refresh(note)
        assert note.status == "dismissed"
        assert note.resolved_at is not None
    assert client.post(f"/api/notes/{comment.id}/dismiss").status_code == 409
    assert client.post(f"/api/notes/{suggestion.id}/dismiss").status_code == 409
    assert client.post("/api/notes/nope/dismiss").status_code == 404


def test_mutating_a_note_tells_the_meeting_page(db_session, monkeypatch):
    import jobs

    meeting, *_ = seed(db_session)
    note = add_note(db_session, meeting, kind="question")
    seen = []
    monkeypatch.setattr(jobs, "notify_meeting_changed", lambda meeting_id: seen.append(meeting_id))
    client = TestClient(app)

    client.post(f"/api/notes/{note.id}/answer", json={"answer": "x"})
    client.post(f"/api/notes/{note.id}/done")

    assert seen == [meeting.id, meeting.id]


def text_note(db, meeting, **kw):
    fields = dict(kind="text", body="parece Garrah", payload={
        "expected_text": "Galo disse isso", "proposed_text": "Garrah disse isso"})
    fields.update(kw)
    return add_note(db, meeting, **fields)


def accept(client, note, **body):
    return client.post(f"/api/notes/{note.id}/accept", json=body)


def test_accepting_a_text_note_edits_the_segment_and_teaches_vocabulary(db_session):
    from models import VocabularyEntry

    meeting, _, _, first, _ = seed(db_session)
    entry = VocabularyEntry(term="Garrah")
    db_session.add(entry)
    note = text_note(db_session, meeting)

    response = accept(TestClient(app), note)

    assert response.status_code == 200
    assert response.json()["warning"] is None
    assert response.json()["note"]["status"] == "accepted"
    db_session.refresh(first)
    db_session.refresh(note)
    db_session.refresh(entry)
    assert first.text == "Garrah disse isso"
    assert first.is_edited
    assert note.status == "accepted"
    assert note.resolved_at is not None
    assert entry.misheard_as == [{"form": "Galo", "count": 1}]


def test_accepting_a_text_note_without_teaching_leaves_vocabulary_alone(db_session):
    from models import VocabularyEntry

    meeting, _, _, first, _ = seed(db_session)
    entry = VocabularyEntry(term="Garrah")
    db_session.add(entry)
    note = text_note(db_session, meeting)

    response = accept(TestClient(app), note, learn=False)

    assert response.status_code == 200
    db_session.refresh(first)
    db_session.refresh(entry)
    assert first.text == "Garrah disse isso"
    assert not entry.misheard_as


def test_accepting_a_text_note_uses_the_segment_at_the_range_now(db_session):
    meeting, _, _, first, _ = seed(db_session)
    first.start_time, first.end_time = 0.8, 5.6
    db_session.commit()
    note = text_note(db_session, meeting)

    assert accept(TestClient(app), note).status_code == 200

    db_session.refresh(first)
    assert first.text == "Garrah disse isso"


def test_accepting_a_text_note_refuses_a_segment_that_changed_since(db_session):
    meeting, _, _, first, _ = seed(db_session)
    note = text_note(db_session, meeting)
    first.text = "editado por outra pessoa"
    db_session.commit()

    response = accept(TestClient(app), note)

    assert response.status_code == 409
    assert response.json()["detail"] == "the Segment changed since the suggestion"
    db_session.refresh(note)
    db_session.refresh(first)
    assert note.status == "open"
    assert first.text == "editado por outra pessoa"


def test_accepting_a_text_note_refuses_a_passage_with_no_segment(db_session):
    meeting, _, _, first, _ = seed(db_session)
    note = text_note(db_session, meeting)
    first.start_time, first.end_time = 30.0, 35.0
    db_session.commit()

    response = accept(TestClient(app), note)

    assert response.status_code == 409
    assert response.json()["detail"] == "the passage no longer matches a Segment"


def test_a_resolved_note_cannot_be_accepted_again(db_session):
    meeting, *_ = seed(db_session)
    note = text_note(db_session, meeting)
    client = TestClient(app)

    assert accept(client, note).status_code == 200
    assert accept(client, note).status_code == 409


def test_only_a_suggestion_can_be_accepted(db_session):
    meeting, *_ = seed(db_session)
    comment = add_note(db_session, meeting, kind="comment")
    question = add_note(db_session, meeting, kind="question")
    client = TestClient(app)

    assert accept(client, comment).status_code == 409
    assert accept(client, question).status_code == 409
    assert accept(client, type("N", (), {"id": "nope"})()).status_code == 404


def test_accepting_during_processing_is_a_conflict(db_session):
    meeting, _, _, first, _ = seed(db_session, status=MeetingStatus.PROCESSING)
    note = text_note(db_session, meeting)

    response = accept(TestClient(app), note)

    assert response.status_code == 409
    db_session.refresh(note)
    db_session.refresh(first)
    assert note.status == "open"
    assert first.text == "Galo disse isso"


def name_note(db, meeting, **kw):
    fields = dict(kind="speaker_name", body="a voz abre a reunião",
                  payload={"label": "SPEAKER_00", "name": "Ana"})
    fields.update(kw)
    return add_note(db, meeting, **fields)


def record_profile_saves(monkeypatch, raises=None):
    calls = []

    def fake(req, db):
        calls.append((req.speaker_id, req.meeting_id, req.name))
        if raises is not None:
            raise raises
        return {}

    monkeypatch.setattr("api.review_notes.save_profile_from_speaker", fake)
    return calls


def test_accepting_a_speaker_name_renames_and_saves_the_voice_profile(db_session, monkeypatch):
    meeting, ana, *_ = seed(db_session)
    calls = record_profile_saves(monkeypatch)
    note = name_note(db_session, meeting)

    response = accept(TestClient(app), note)

    assert response.status_code == 200
    assert response.json()["warning"] is None
    db_session.refresh(ana)
    db_session.refresh(note)
    assert ana.display_name == "Ana"
    assert ana.identified_by == "manual"
    assert note.status == "accepted"
    assert calls == [(ana.id, meeting.id, "Ana")]


def test_accepting_a_speaker_name_without_saving_the_profile_only_renames(db_session, monkeypatch):
    meeting, ana, *_ = seed(db_session)
    calls = record_profile_saves(monkeypatch)
    note = name_note(db_session, meeting)

    response = accept(TestClient(app), note, save_profile=False)

    assert response.status_code == 200
    db_session.refresh(ana)
    assert ana.display_name == "Ana"
    assert calls == []


def test_a_voice_profile_failure_keeps_the_rename_and_warns(db_session, monkeypatch):
    from fastapi import HTTPException

    meeting, ana, *_ = seed(db_session)
    record_profile_saves(monkeypatch, raises=HTTPException(404, "Meeting or audio not found"))
    note = name_note(db_session, meeting)

    response = accept(TestClient(app), note)

    assert response.status_code == 200
    assert response.json()["warning"] == "Voice Profile not saved: Meeting or audio not found"
    db_session.refresh(ana)
    db_session.refresh(note)
    assert ana.display_name == "Ana"
    assert note.status == "accepted"


def test_an_ffmpeg_failure_also_keeps_the_rename_and_warns(db_session, monkeypatch):
    meeting, ana, *_ = seed(db_session)
    record_profile_saves(monkeypatch, raises=RuntimeError("FFmpeg failed: boom"))
    note = name_note(db_session, meeting)

    response = accept(TestClient(app), note)

    assert response.status_code == 200
    assert "FFmpeg failed: boom" in response.json()["warning"]
    db_session.refresh(ana)
    assert ana.display_name == "Ana"


def test_accepting_a_speaker_name_for_a_vanished_speaker_is_a_conflict(db_session):
    meeting, *_ = seed(db_session)
    note = name_note(db_session, meeting, payload={"label": "SPEAKER_07", "name": "Ana"})

    assert accept(TestClient(app), note).status_code == 409


def test_accepting_a_speaker_move_moves_the_segment_to_the_target(db_session):
    meeting, ana, bia, first, _ = seed(db_session)
    note = add_note(db_session, meeting, kind="speaker_move", body="e a Bia",
                    payload={"target_label": "SPEAKER_01"})

    response = accept(TestClient(app), note)

    assert response.status_code == 200
    db_session.refresh(first)
    db_session.refresh(note)
    assert first.speaker_id == bia.id
    assert first.speaker_edited
    assert note.status == "accepted"


def test_accepting_a_speaker_move_to_a_new_speaker_adds_it(db_session):
    meeting, _, _, first, _ = seed(db_session)
    note = add_note(db_session, meeting, kind="speaker_move", body="uma terceira voz",
                    payload={"new_name": "Carla"})

    response = accept(TestClient(app), note)

    assert response.status_code == 200
    db_session.refresh(first)
    carla = db_session.get(Speaker, first.speaker_id)
    assert carla.display_name == "Carla"
    assert carla.label == "MANUAL_1"


def test_accepting_a_speaker_move_with_no_segment_at_the_range_is_a_conflict(db_session):
    meeting, *_ = seed(db_session)
    note = add_note(db_session, meeting, kind="speaker_move", body="x",
                    start_time=30.0, end_time=35.0, payload={"target_label": "SPEAKER_01"})

    assert accept(TestClient(app), note).status_code == 409


def test_accepting_a_speaker_merge_merges_the_speakers(db_session):
    meeting, ana, bia, first, second = seed(db_session)
    note = add_note(db_session, meeting, kind="speaker_merge", body="mesma voz",
                    payload={"source_label": "SPEAKER_00", "target_label": "SPEAKER_01"})

    response = accept(TestClient(app), note)

    assert response.status_code == 200
    db_session.expire_all()
    assert db_session.query(Speaker).filter(Speaker.meeting_id == meeting.id).count() == 1
    assert db_session.get(Segment, first.id).speaker_id == bia.id
    assert db_session.get(ReviewNote, note.id).status == "accepted"


def test_accepting_a_speaker_merge_with_a_vanished_speaker_is_a_conflict(db_session):
    meeting, *_ = seed(db_session)
    note = add_note(db_session, meeting, kind="speaker_merge", body="x",
                    payload={"source_label": "SPEAKER_00", "target_label": "SPEAKER_07"})

    assert accept(TestClient(app), note).status_code == 409


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
