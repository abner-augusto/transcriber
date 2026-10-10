import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

import jobs
from main import app
from models import Meeting, MeetingStatus, RejectedForm, Segment, Speaker, VocabularyEntry
from models.job import Job, JobType


class FakeHealth:
    def to_dict(self):
        return {
            "state": "blocked", "summary": "runtime mismatch", "checks": [],
            "fingerprint": "fixture", "available": False, "reason": "runtime mismatch",
        }


def test_update_meeting_title_and_vocabulary(db_session):
    client = TestClient(app)

    meeting = Meeting(
        title="Original Title",
        status=MeetingStatus.UPLOADED,
        vocabulary="Initial Word",
    )
    db_session.add(meeting)
    db_session.commit()
    meeting_id = meeting.id

    # Update vocabulary only
    resp = client.put(f"/api/meetings/{meeting_id}", json={"vocabulary": "Alice, Bob, Charlie"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Original Title"
    assert data["vocabulary"] == "Alice, Bob, Charlie"

    # Update title only
    resp = client.put(f"/api/meetings/{meeting_id}", json={"title": "Updated Title"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Updated Title"
    assert data["vocabulary"] == "Alice, Bob, Charlie"

    # Clear vocabulary
    resp = client.put(f"/api/meetings/{meeting_id}", json={"vocabulary": ""})
    assert resp.status_code == 200
    data = resp.json()
    assert data["vocabulary"] is None

    # Update both
    resp = client.put(f"/api/meetings/{meeting_id}", json={"title": "Final Title", "vocabulary": "Dan, Eve"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Final Title"
    assert data["vocabulary"] == "Dan, Eve"

    # Multiline structured vocabulary (speakers + terms)
    multiline_vocab = "Speakers: Alice, Bob\nVocabulary: Docker, Kubernetes"
    resp = client.put(f"/api/meetings/{meeting_id}", json={"vocabulary": multiline_vocab})
    assert resp.status_code == 200
    assert resp.json()["vocabulary"] == multiline_vocab


def test_update_nonexistent_meeting(db_session):
    client = TestClient(app)
    resp = client.put("/api/meetings/nonexistent-id", json={"title": "New Title"})
    assert resp.status_code == 404


def test_meeting_list_never_reads_the_raw_engine_output(db_session):
    """The raw JSON columns run to megabytes per Meeting; the list does not show them."""
    meeting = Meeting(
        title="Obra 12", status=MeetingStatus.COMPLETED,
        raw_transcription={"segments": []}, raw_diarization={"turns": []}, split_times=[60.0],
    )
    db_session.add(meeting)
    db_session.commit()
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", record)
    try:
        resp = TestClient(app).get("/api/meetings")
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert resp.status_code == 200
    assert [m["title"] for m in resp.json()] == ["Obra 12"]
    sql = " ".join(statements)
    for column in ("raw_transcription", "raw_diarization", "split_times"):
        assert column not in sql


def test_blocked_preset_cannot_create_or_queue_job(db_session, monkeypatch):
    client = TestClient(app)
    meeting = Meeting(title="Blocked", status=MeetingStatus.UPLOADED, preset_id="blocked")
    db_session.add(meeting)
    db_session.commit()
    meeting_id = meeting.id
    monkeypatch.setattr("api.meetings.presets.resolve_preset", lambda _preset_id: {
        "id": "blocked", "name": "Blocked", "engine": "vibevoice", "model_path": "missing"
    })
    monkeypatch.setattr("api.meetings.probe_engine", lambda _preset: FakeHealth())
    queued = []
    runner = app.state.test_job_runner

    response = client.post(f"/api/meetings/{meeting_id}/process")

    assert response.status_code == 409
    assert response.json()["detail"]["health"]["state"] == "blocked"
    db_session.refresh(meeting)
    assert meeting.status == MeetingStatus.UPLOADED
    assert db_session.query(Job).count() == 0
    assert runner.submitted == []


@pytest.mark.parametrize("route", ["process", "rediarize", "duplicate"])
def test_blocked_diarizer_refuses_queueing_with_409(db_session, monkeypatch, tmp_path, route):
    audio = tmp_path / "meeting.wav"
    audio.write_bytes(b"RIFF")
    meeting = Meeting(title="Blocked Diarizer", status=MeetingStatus.COMPLETED,
        audio_filepath=str(audio), raw_transcription={"words": []})
    db_session.add(meeting)
    db_session.commit()
    ready = {"id": "ready", "name": "Ready", "engine": "parakeet.cpp", "model_path": "m"}
    monkeypatch.setattr("api.meetings.presets.resolve_preset", lambda _preset_id: ready)
    monkeypatch.setattr("api.meetings.presets.get_preset", lambda _preset_id: ready)
    monkeypatch.setattr("api.meetings.probe_engine", lambda _preset: type(
        "Ready", (), {"to_dict": lambda self: {"state": "ready", "summary": "ready"}})())
    # Fresh Preferences, not the machine's: the default Diarizer is pyannote.
    monkeypatch.setattr("config.settings.storage_path", str(tmp_path / "storage"))
    seen = []
    monkeypatch.setattr("api.meetings.diarizer_status", lambda engine, **_kwargs: seen.append(engine) or {
        "state": "blocked", "summary": "Dedicated runtime not found"})

    client = TestClient(app)
    if route == "duplicate":
        response = client.post(f"/api/meetings/{meeting.id}/duplicate", json={"preset_id": "ready"})
    else:
        response = client.post(f"/api/meetings/{meeting.id}/{route}")

    assert response.status_code == 409
    assert response.json()["detail"]["message"] == "Dedicated runtime not found"
    assert seen == ["pyannote"]
    assert db_session.query(Job).count() == 0
    assert db_session.query(Meeting).count() == 1


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        ("process", JobType.PROCESS_MEETING),
        ("rediarize", JobType.REDIARIZE),
        ("reidentify", JobType.REIDENTIFY),
        ("reapply-vocabulary", JobType.REAPPLY_VOCABULARY),
    ],
)
def test_enqueue_routes_claim_once_and_submit_one_job(db_session, monkeypatch, path, kind):
    meeting = Meeting(
        title="Enqueue", status=MeetingStatus.COMPLETED, audio_filepath="meeting.wav",
        preset_id="test",
        raw_transcription={"words": [{"start": 0.0, "end": 0.4, "text": " Galo"}]},
        raw_diarization={"turns": [{"start": 0, "end": 1, "speaker": "SPEAKER_00"}]},
    )
    db_session.add(meeting)
    db_session.commit()
    monkeypatch.setattr("api.meetings.presets.resolve_preset", lambda _preset_id: {
        "id": "test", "name": "Test", "engine": "test", "model_path": "test-model"
    })
    class ReadyHealth:
        def to_dict(self):
            return {"state": "ready", "summary": "ready"}
    monkeypatch.setattr("api.meetings.probe_engine", lambda _preset: ReadyHealth())
    monkeypatch.setattr("api.meetings._require_usable_diarizer", lambda: {"state": "ready"})
    runner = app.state.test_job_runner

    client = TestClient(app)
    response = client.post(f"/api/meetings/{meeting.id}/{path}")

    assert response.status_code == 200
    job_id = response.json()["id"]
    assert response.json()["job_type"] == kind.value
    assert runner.submitted == [(meeting.id, job_id, kind)]
    db_session.refresh(meeting)
    assert meeting.status == MeetingStatus.PROCESSING
    assert db_session.query(Job).count() == 1

    duplicate = client.post(f"/api/meetings/{meeting.id}/{path}")
    assert duplicate.status_code == 409
    assert runner.submitted == [(meeting.id, job_id, kind)]
    assert db_session.query(Job).count() == 1


def test_processing_meeting_is_rejected_before_preset_health(db_session, monkeypatch):
    meeting = Meeting(
        title="Already processing", status=MeetingStatus.PROCESSING, preset_id="invalid"
    )
    db_session.add(meeting)
    db_session.commit()
    monkeypatch.setattr(
        "api.meetings.presets.resolve_preset",
        lambda _preset_id: pytest.fail("preset health must not run for a processing Meeting"),
    )

    response = TestClient(app).post(f"/api/meetings/{meeting.id}/process")

    assert response.status_code == 409
    assert response.json()["detail"] == "Meeting is already being processed"
    assert db_session.query(Job).count() == 0


def test_losing_atomic_claim_returns_conflict(db_session, monkeypatch):
    meeting = Meeting(
        title="Claim race", status=MeetingStatus.COMPLETED,
        preset_id="test", audio_filepath="meeting.wav",
    )
    db_session.add(meeting)
    db_session.commit()

    class ReadyHealth:
        def to_dict(self):
            return {"state": "ready", "summary": "ready"}

    monkeypatch.setattr("api.meetings.presets.resolve_preset", lambda _id: {"id": "test"})
    monkeypatch.setattr("api.meetings.probe_engine", lambda _preset: ReadyHealth())
    monkeypatch.setattr("api.meetings.diarizer_status", lambda _engine, **_kwargs: {
        "state": "ready", "summary": "ready"})
    calls = []

    def lose_race(*args):
        calls.append(args)
        raise jobs.JobAlreadyRunning("claimed by another request")

    monkeypatch.setattr("api.meetings.jobs.enqueue", lose_race)
    response = TestClient(app).post(f"/api/meetings/{meeting.id}/process")

    assert response.status_code == 409
    assert response.json()["detail"] == "Meeting is already being processed"
    assert len(calls) == 1
    assert db_session.query(Job).count() == 0


def test_websocket_forwards_progress_event_in_existing_shape(db_session):
    import time

    meeting = Meeting(title="Progress", status=MeetingStatus.PROCESSING)
    db_session.add(meeting)
    db_session.commit()
    bus = app.state.test_progress_bus
    event = {
        "type": "progress", "progress": 48, "step": "Transcription complete",
        "status": "processing",
    }

    with TestClient(app).websocket_connect(f"/ws/meetings/{meeting.id}") as websocket:
        deadline = time.monotonic() + 2
        while bus.subscriber_count(meeting.id) == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert bus.subscriber_count(meeting.id) == 1
        bus.publish(meeting.id, event)
        assert websocket.receive_json() == event


def test_segment_edits_learn_and_increment_misheard_form(db_session):
    meeting = Meeting(title="Learning", status=MeetingStatus.COMPLETED)
    entry = VocabularyEntry(term="Garrah")
    db_session.add_all([meeting, entry])
    db_session.flush()
    segment = Segment(
        meeting_id=meeting.id, start_time=0, end_time=0.5,
        text="o Galo", original_text="o Galo", order=0,
    )
    db_session.add(segment)
    db_session.commit()

    client = TestClient(app)
    for _ in range(2):
        response = client.put(f"/api/segments/{segment.id}", json={"text": "o Garrah"})
        assert response.status_code == 200
        assert response.json()["text"] == "o Garrah"

    db_session.refresh(entry)
    assert entry.misheard_as == [{"form": "Galo", "count": 2, "confirmed": False}]


def _meeting_with_segments(db_session, texts, **meeting_fields):
    meeting = Meeting(title="Gate", status=MeetingStatus.COMPLETED, **meeting_fields)
    db_session.add(meeting)
    db_session.flush()
    segments = [
        Segment(
            meeting_id=meeting.id, start_time=float(order), end_time=order + 0.5,
            text=text, original_text=text, order=order,
        )
        for order, text in enumerate(texts)
    ]
    db_session.add_all(segments)
    db_session.commit()
    return meeting, segments


def test_a_sentence_initial_name_is_learned_when_the_meeting_capitalizes_it_elsewhere(db_session):
    entry = VocabularyEntry(term="Garrah")
    db_session.add(entry)
    _, (target, _) = _meeting_with_segments(db_session, ["Galo disse isso", "falei com o Garrah hoje"])

    response = TestClient(app).put(f"/api/segments/{target.id}", json={"text": "Garrah disse isso"})

    assert response.status_code == 200
    db_session.refresh(entry)
    assert entry.misheard_as == [{"form": "Galo", "count": 1, "confirmed": False}]


def test_an_edit_of_common_words_teaches_no_vocabulary(db_session):
    _, (target,) = _meeting_with_segments(db_session, ["e tu falou com ele"])

    response = TestClient(app).put(f"/api/segments/{target.id}", json={"text": "e o valor com ele"})

    assert response.status_code == 200
    assert db_session.query(VocabularyEntry).count() == 0


def test_an_edit_to_a_term_of_the_meeting_vocabulary_is_learned_in_lowercase(db_session):
    _, (target,) = _meeting_with_segments(
        db_session, ["sem habitese hoje"], vocabulary="habite-se"
    )

    response = TestClient(app).put(f"/api/segments/{target.id}", json={"text": "sem habite-se hoje"})

    assert response.status_code == 200
    entry = db_session.query(VocabularyEntry).filter_by(term="habite-se").one()
    assert entry.misheard_as == [{"form": "habitese", "count": 1, "confirmed": False}]


def test_an_edit_to_a_participant_name_is_learned_in_lowercase(db_session):
    _, (target,) = _meeting_with_segments(
        db_session, ["falou o buno hoje"], participants="ana maria\nbruno"
    )

    response = TestClient(app).put(f"/api/segments/{target.id}", json={"text": "falou o bruno hoje"})

    assert response.status_code == 200
    entry = db_session.query(VocabularyEntry).filter_by(term="bruno").one()
    assert entry.misheard_as == [{"form": "buno", "count": 1, "confirmed": False}]


def test_an_edit_teaching_a_new_term_records_its_misheard_form(db_session):
    meeting = Meeting(title="New term", status=MeetingStatus.COMPLETED)
    db_session.add(meeting)
    db_session.flush()
    segment = Segment(
        meeting_id=meeting.id, start_time=0, end_time=2.0, order=0,
        text="Quem mandou o Infarmacom", original_text="Quem mandou o Infarmacom",
    )
    db_session.add(segment)
    db_session.commit()

    response = TestClient(app).put(
        f"/api/segments/{segment.id}", json={"text": "Quem mandou o Informakon"}
    )

    assert response.status_code == 200
    entry = db_session.query(VocabularyEntry).filter_by(term="Informakon").one()
    assert entry.misheard_as == [{"form": "Infarmacom", "count": 1, "confirmed": False}]


def test_undoing_a_correction_by_hand_teaches_nothing_and_clears_corrections(db_session):
    meeting = Meeting(title="Undo", status=MeetingStatus.COMPLETED)
    db_session.add_all([meeting, VocabularyEntry(term="Garrah")])
    db_session.flush()
    segment = Segment(
        meeting_id=meeting.id, start_time=0, end_time=1.0,
        text="Garrah confirmou", original_text="Garrah confirmou", order=0,
        corrections=[{
            "start": 0.0, "end": 0.4, "heard": "Galo", "term": "Garrah", "rule": "similar",
        }],
    )
    db_session.add(segment)
    db_session.commit()
    client = TestClient(app)

    response = client.put(f"/api/segments/{segment.id}", json={"text": "Galo confirmou"})

    assert response.status_code == 200
    assert response.json()["corrections"] == []
    vocabulary = client.get("/api/vocabulary").json()
    assert [(entry["term"], entry["misheard_as"]) for entry in vocabulary] == [("Garrah", [])]


def test_one_misheard_form_can_be_deleted_without_the_term(db_session):
    entry = VocabularyEntry(
        term="Garrah", misheard_as=[{"form": "Galo", "count": 2}, {"form": "Garra", "count": 1}],
    )
    db_session.add(entry)
    db_session.commit()
    client = TestClient(app)

    response = client.delete(f"/api/vocabulary/{entry.id}/misheard-forms/Galo")

    assert response.status_code == 200
    vocabulary = client.get("/api/vocabulary").json()
    assert [(e["term"], e["misheard_as"]) for e in vocabulary] == [
        ("Garrah", [{"form": "Garra", "count": 1}])
    ]
    missing = client.delete(f"/api/vocabulary/{entry.id}/misheard-forms/Galo")
    assert missing.status_code == 404


def _meeting_with_words(db_session):
    meeting = Meeting(
        title="Words",
        status=MeetingStatus.COMPLETED,
        raw_transcription={
            "words": [
                {"start": 0, "end": 0.4, "text": " Galo", "confidence": 0.31, "alignment_score": None},
                {"start": 0.5, "end": 0.9, "text": " confirmou", "confidence": 0.92, "alignment_score": None},
            ]
        },
    )
    db_session.add(meeting)
    db_session.commit()
    return meeting.id


def test_words_returns_stored_words_with_confidence(db_session):
    meeting_id = _meeting_with_words(db_session)
    client = TestClient(app)

    response = client.get(f"/api/meetings/{meeting_id}/words")

    assert response.status_code == 200
    words = response.json()
    assert [w["text"] for w in words] == [" Galo", " confirmou"]
    assert [w["confidence"] for w in words] == [0.31, 0.92]
    assert set(words[0]) == {"start", "end", "text", "confidence", "alignment_score"}


def test_words_filters_by_time_range(db_session):
    meeting_id = _meeting_with_words(db_session)
    client = TestClient(app)

    response = client.get(f"/api/meetings/{meeting_id}/words", params={"start": 0.45, "end": 1})

    assert response.status_code == 200
    assert [w["text"] for w in response.json()] == [" confirmou"]


def test_words_of_an_untranscribed_meeting_is_empty(db_session):
    meeting = Meeting(title="Fresh", status=MeetingStatus.UPLOADED)
    db_session.add(meeting)
    db_session.commit()
    client = TestClient(app)

    response = client.get(f"/api/meetings/{meeting.id}/words")

    assert response.status_code == 200
    assert response.json() == []


def test_words_rejects_inverted_range(db_session):
    meeting_id = _meeting_with_words(db_session)
    client = TestClient(app)

    response = client.get(f"/api/meetings/{meeting_id}/words", params={"start": 5, "end": 1})

    assert response.status_code == 400
    assert response.json()["detail"] == "start must not exceed end"


def test_words_of_missing_meeting_is_404(db_session):
    client = TestClient(app)

    response = client.get("/api/meetings/does-not-exist/words")

    assert response.status_code == 404
    assert response.json()["detail"] == "Meeting not found"


def _meeting_with_speakers(db_session, status=MeetingStatus.COMPLETED):
    meeting = Meeting(title="Edits", status=status)
    db_session.add(meeting)
    db_session.flush()
    first = Speaker(meeting_id=meeting.id, label="SPEAKER_00", display_name="A")
    second = Speaker(meeting_id=meeting.id, label="SPEAKER_01", display_name="B")
    db_session.add_all([first, second])
    db_session.flush()
    return meeting, first, second


def test_segment_edit_is_refused_while_the_meeting_is_processing(db_session):
    meeting = Meeting(title="Busy", status=MeetingStatus.PROCESSING)
    db_session.add(meeting)
    db_session.flush()
    segment = Segment(
        meeting_id=meeting.id, start_time=0, end_time=1.0,
        text="Galo", original_text="Galo", order=0,
    )
    db_session.add(segment)
    db_session.commit()

    response = TestClient(app).put(f"/api/segments/{segment.id}", json={"text": "Garrah"})

    assert response.status_code == 409
    db_session.refresh(segment)
    assert segment.text == "Galo"


def test_reassigning_a_segment_updates_both_speakers_stats(db_session):
    meeting, first, second = _meeting_with_speakers(db_session)
    kept = Segment(
        meeting_id=meeting.id, speaker_id=first.id, start_time=0, end_time=1.0,
        text="one", original_text="one", order=0,
    )
    moved = Segment(
        meeting_id=meeting.id, speaker_id=first.id, start_time=1.0, end_time=3.0,
        text="two", original_text="two", order=1,
    )
    first.segment_count, first.total_speaking_time = 2, 3.0
    db_session.add_all([kept, moved])
    db_session.commit()

    response = TestClient(app).put(
        f"/api/segments/{moved.id}/speaker", json={"speaker_id": second.id}
    )

    assert response.status_code == 200
    db_session.refresh(first)
    db_session.refresh(second)
    assert (first.segment_count, first.total_speaking_time) == (1, 1.0)
    assert (second.segment_count, second.total_speaking_time) == (1, 2.0)


def test_reassigning_to_a_speaker_of_another_meeting_is_rejected(db_session):
    meeting, first, _ = _meeting_with_speakers(db_session)
    _, foreign, _ = _meeting_with_speakers(db_session)
    segment = Segment(
        meeting_id=meeting.id, speaker_id=first.id, start_time=0, end_time=1.0,
        text="one", original_text="one", order=0,
    )
    db_session.add(segment)
    db_session.commit()

    response = TestClient(app).put(
        f"/api/segments/{segment.id}/speaker", json={"speaker_id": foreign.id}
    )

    assert response.status_code == 400
    db_session.refresh(segment)
    assert segment.speaker_id == first.id


def test_reassigning_to_a_missing_speaker_is_404(db_session):
    meeting, first, _ = _meeting_with_speakers(db_session)
    segment = Segment(
        meeting_id=meeting.id, speaker_id=first.id, start_time=0, end_time=1.0,
        text="one", original_text="one", order=0,
    )
    db_session.add(segment)
    db_session.commit()

    response = TestClient(app).put(
        f"/api/segments/{segment.id}/speaker", json={"speaker_id": "no-such-speaker"}
    )

    assert response.status_code == 404
    db_session.refresh(segment)
    assert segment.speaker_id == first.id


def test_segment_edit_with_learn_false_teaches_nothing(db_session):
    meeting = Meeting(title="Quiet", status=MeetingStatus.COMPLETED)
    entry = VocabularyEntry(term="Garrah")
    db_session.add_all([meeting, entry])
    db_session.flush()
    segment = Segment(
        meeting_id=meeting.id, start_time=0, end_time=0.5,
        text="Galo", original_text="Galo", order=0,
    )
    db_session.add(segment)
    db_session.commit()

    response = TestClient(app).put(
        f"/api/segments/{segment.id}", json={"text": "Garrah", "learn": False}
    )

    assert response.status_code == 200
    assert response.json()["text"] == "Garrah"
    db_session.refresh(entry)
    assert entry.misheard_as == []
    assert db_session.query(VocabularyEntry).count() == 1


def test_revert_restores_the_derived_text(db_session):
    meeting = Meeting(title="Revert", status=MeetingStatus.COMPLETED)
    db_session.add_all([meeting, VocabularyEntry(term="Garrah")])
    db_session.flush()
    segment = Segment(
        meeting_id=meeting.id, start_time=0, end_time=0.5,
        text="Galo", original_text="Galo", order=0,
    )
    db_session.add(segment)
    db_session.commit()
    client = TestClient(app)
    client.put(f"/api/segments/{segment.id}", json={"text": "Garrah", "learn": False})
    vocabulary_before = client.get("/api/vocabulary").json()

    response = client.post(f"/api/segments/{segment.id}/revert")

    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "Galo"
    assert body["is_edited"] is False
    assert client.get("/api/vocabulary").json() == vocabulary_before


def test_revert_of_an_unedited_segment_is_409(db_session):
    meeting = Meeting(title="Unedited", status=MeetingStatus.COMPLETED)
    db_session.add(meeting)
    db_session.flush()
    segment = Segment(
        meeting_id=meeting.id, start_time=0, end_time=0.5,
        text="Galo", original_text="Galo", order=0,
    )
    db_session.add(segment)
    db_session.commit()

    response = TestClient(app).post(f"/api/segments/{segment.id}/revert")

    assert response.status_code == 409


def test_add_speaker_gets_the_next_manual_label(db_session):
    meeting, _, _ = _meeting_with_speakers(db_session)
    db_session.add(Speaker(meeting_id=meeting.id, label="MANUAL_1", display_name="Eve"))
    db_session.commit()

    response = TestClient(app).post(
        f"/api/meetings/{meeting.id}/speakers", json={"display_name": "  Carol "}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["label"] == "MANUAL_2"
    assert body["display_name"] == "Carol"
    assert body["identified_by"] == "manual"
    assert (body["segment_count"], body["total_speaking_time"]) == (0, 0.0)


def test_add_speaker_requires_a_name(db_session):
    meeting, _, _ = _meeting_with_speakers(db_session)
    db_session.commit()

    response = TestClient(app).post(
        f"/api/meetings/{meeting.id}/speakers", json={"display_name": "   "}
    )

    assert response.status_code == 400


def _edit_targets(db_session):
    """A completed Meeting with two Speakers and one edited Segment, for the edit routes."""
    meeting, first, second = _meeting_with_speakers(db_session)
    segment = Segment(
        meeting_id=meeting.id, speaker_id=first.id, start_time=0, end_time=1.0,
        text="Garrah", original_text="Galo", is_edited=True, order=0,
    )
    db_session.add(segment)
    db_session.commit()
    return meeting, first, second, segment


def _events_caused_by(meeting_id, act):
    """Open the Meeting's socket, run `act`, then a sentinel; return what arrived before the sentinel."""
    import time

    bus = app.state.test_progress_bus
    sentinel = {"type": "ping"}
    with TestClient(app).websocket_connect(f"/ws/meetings/{meeting_id}") as websocket:
        deadline = time.monotonic() + 2
        while bus.subscriber_count(meeting_id) == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert bus.subscriber_count(meeting_id) == 1
        act()
        bus.publish(meeting_id, sentinel)
        events = [websocket.receive_json()]
        while events[-1] != sentinel:
            events.append(websocket.receive_json())
    return events[:-1]


def test_segment_edit_publishes_meeting_changed(db_session):
    meeting, _, _, segment = _edit_targets(db_session)
    client = TestClient(app)

    events = _events_caused_by(
        meeting.id,
        lambda: client.put(f"/api/segments/{segment.id}", json={"text": "novo"}),
    )

    assert events == [{"type": "meeting_changed"}]


def test_speaker_rename_publishes_meeting_changed(db_session):
    meeting, first, _, _ = _edit_targets(db_session)
    client = TestClient(app)

    events = _events_caused_by(
        meeting.id,
        lambda: client.put(f"/api/speakers/{first.id}", json={"display_name": "Ana"}),
    )

    assert events == [{"type": "meeting_changed"}]


@pytest.mark.parametrize("route", [
    "revert", "segment_speaker", "merge", "add_speaker", "meeting_details",
])
def test_every_other_edit_route_publishes_meeting_changed(db_session, route):
    meeting, first, second, segment = _edit_targets(db_session)
    client = TestClient(app)
    requests = {
        "revert": lambda: client.post(f"/api/segments/{segment.id}/revert"),
        "segment_speaker": lambda: client.put(
            f"/api/segments/{segment.id}/speaker", json={"speaker_id": second.id}),
        "merge": lambda: client.post(
            "/api/speakers/merge", json={"source_id": first.id, "target_id": second.id}),
        "add_speaker": lambda: client.post(
            f"/api/meetings/{meeting.id}/speakers", json={"display_name": "Carol"}),
        "meeting_details": lambda: client.put(
            f"/api/meetings/{meeting.id}", json={"title": "Renamed"}),
    }

    events = _events_caused_by(meeting.id, requests[route])

    assert events == [{"type": "meeting_changed"}]


def test_failed_edit_publishes_nothing(db_session):
    meeting = Meeting(title="Busy", status=MeetingStatus.PROCESSING)
    db_session.add(meeting)
    db_session.flush()
    segment = Segment(
        meeting_id=meeting.id, start_time=0, end_time=1.0,
        text="Galo", original_text="Galo", order=0,
    )
    db_session.add(segment)
    db_session.commit()
    client = TestClient(app)
    statuses = []

    events = _events_caused_by(
        meeting.id,
        lambda: statuses.append(client.put(f"/api/segments/{segment.id}", json={"text": "novo"}).status_code),
    )

    assert statuses == [409]
    assert events == []


def test_read_routes_publish_nothing(db_session):
    meeting, _, _, _ = _edit_targets(db_session)
    client = TestClient(app)

    events = _events_caused_by(
        meeting.id,
        lambda: [client.get(f"/api/meetings/{meeting.id}/segments"), client.get(f"/api/meetings/{meeting.id}/words")],
    )

    assert events == []


def _meeting_to_split(db_session, status=MeetingStatus.COMPLETED):
    """Six Words w0..w5 (a Word every 0.5 s); Segment 0 holds w0..w3, Segment 1 holds w4 w5."""
    meeting = Meeting(
        title="Split",
        status=status,
        raw_transcription={
            "words": [
                {"start": i * 0.5, "end": i * 0.5 + 0.4, "text": f" w{i}", "confidence": 0.9}
                for i in range(6)
            ]
        },
    )
    db_session.add(meeting)
    db_session.flush()
    first = Speaker(meeting_id=meeting.id, label="SPEAKER_00", display_name="A")
    second = Speaker(meeting_id=meeting.id, label="SPEAKER_01", display_name="B")
    db_session.add_all([first, second])
    db_session.flush()
    joined = Segment(
        meeting_id=meeting.id, speaker_id=first.id, start_time=0.0, end_time=1.9,
        text="w0 w1 w2 w3", original_text="w0 w1 w2 w3", order=0,
    )
    after = Segment(
        meeting_id=meeting.id, speaker_id=first.id, start_time=2.0, end_time=2.9,
        text="w4 w5", original_text="w4 w5", order=1,
    )
    first.segment_count, first.total_speaking_time = 2, 2.8
    db_session.add_all([joined, after])
    db_session.commit()
    return meeting, first, second, joined, after


def test_a_split_snaps_to_the_nearest_word_start(db_session, isolated_preferences):
    meeting, _, _, joined, after = _meeting_to_split(db_session)

    response = TestClient(app).post(f"/api/segments/{joined.id}/split", json={"at": 0.9})

    assert response.status_code == 200
    halves = response.json()["segments"]
    assert [(h["text"], h["start_time"], h["end_time"], h["order"]) for h in halves] == [
        ("w0 w1", 0.0, 0.9, 0),
        ("w2 w3", 1.0, 1.9, 1),
    ]
    assert halves[0]["id"] == joined.id
    db_session.refresh(after)
    db_session.refresh(meeting)
    assert after.order == 2
    assert meeting.split_times == [1.0]


def test_a_split_can_hand_the_second_half_to_another_speaker(db_session, isolated_preferences):
    meeting, first, second, joined, _ = _meeting_to_split(db_session)

    response = TestClient(app).post(
        f"/api/segments/{joined.id}/split", json={"at": 1.0, "speaker_id": second.id},
    )

    assert response.status_code == 200
    kept, moved = response.json()["segments"]
    assert (kept["speaker_id"], kept["speaker_edited"]) == (first.id, False)
    assert (moved["speaker_id"], moved["speaker_edited"]) == (second.id, True)
    db_session.refresh(first)
    db_session.refresh(second)
    assert first.segment_count == 2
    assert first.total_speaking_time == pytest.approx(0.9 + 0.9)
    assert second.segment_count == 1
    assert second.total_speaking_time == pytest.approx(0.9)


def test_a_split_to_a_speaker_of_another_meeting_is_rejected(db_session, isolated_preferences):
    _, _, _, joined, _ = _meeting_to_split(db_session)
    _, stranger, _ = _meeting_with_speakers(db_session)
    db_session.commit()
    client = TestClient(app)

    wrong_meeting = client.post(
        f"/api/segments/{joined.id}/split", json={"at": 1.0, "speaker_id": stranger.id},
    )
    missing = client.post(
        f"/api/segments/{joined.id}/split", json={"at": 1.0, "speaker_id": "nobody"},
    )

    assert (wrong_meeting.status_code, missing.status_code) == (400, 404)


def test_a_split_of_an_edited_segment_is_refused(db_session, isolated_preferences):
    meeting, _, _, joined, _ = _meeting_to_split(db_session)
    joined.is_edited = True
    db_session.commit()

    response = TestClient(app).post(f"/api/segments/{joined.id}/split", json={"at": 1.0})

    assert response.status_code == 409
    assert "revert the edit first" in response.json()["detail"]


def test_a_one_word_segment_has_no_boundary_to_split_at(db_session, isolated_preferences):
    _, _, _, _, after = _meeting_to_split(db_session)
    after.text = after.original_text = "w4"
    after.end_time = 2.4
    db_session.commit()

    response = TestClient(app).post(f"/api/segments/{after.id}/split", json={"at": 2.2})

    assert response.status_code == 409
    assert "no Word boundary" in response.json()["detail"]


def test_a_split_is_refused_while_the_meeting_is_processing(db_session, isolated_preferences):
    _, _, _, joined, _ = _meeting_to_split(db_session, status=MeetingStatus.PROCESSING)

    response = TestClient(app).post(f"/api/segments/{joined.id}/split", json={"at": 1.0})

    assert response.status_code == 409


def test_a_missing_segment_cannot_be_split(db_session, isolated_preferences):
    assert TestClient(app).post("/api/segments/nope/split", json={"at": 1.0}).status_code == 404
    assert TestClient(app).post("/api/segments/nope/unsplit").status_code == 404


def test_unsplit_joins_the_halves_again(db_session, isolated_preferences):
    meeting, first, _, joined, after = _meeting_to_split(db_session)
    client = TestClient(app)
    client.post(f"/api/segments/{joined.id}/split", json={"at": 1.0})

    response = client.post(f"/api/segments/{joined.id}/unsplit")

    assert response.status_code == 200
    body = response.json()
    assert (body["id"], body["text"], body["start_time"], body["end_time"], body["order"]) == (
        joined.id, "w0 w1 w2 w3", 0.0, 1.9, 0,
    )
    db_session.expire_all()
    assert [(s.text, s.order) for s in db_session.query(Segment).order_by(Segment.order)] == [
        ("w0 w1 w2 w3", 0), ("w4 w5", 1),
    ]
    assert db_session.get(Meeting, meeting.id).split_times == []
    assert db_session.get(Speaker, first.id).segment_count == 2


def test_unsplit_without_a_split_is_409(db_session, isolated_preferences):
    _, _, _, joined, _ = _meeting_to_split(db_session)

    response = TestClient(app).post(f"/api/segments/{joined.id}/unsplit")

    assert response.status_code == 409
    assert "no Split after this Segment" in response.json()["detail"]


def test_unsplit_refuses_an_edited_half(db_session, isolated_preferences):
    _, _, _, joined, _ = _meeting_to_split(db_session)
    client = TestClient(app)
    client.post(f"/api/segments/{joined.id}/split", json={"at": 1.0})
    client.put(f"/api/segments/{joined.id}", json={"text": "novo", "learn": False})

    response = client.post(f"/api/segments/{joined.id}/unsplit")

    assert response.status_code == 409
    assert "revert the edit first" in response.json()["detail"]


def _meeting_with_corrections(db_session, status=MeetingStatus.COMPLETED, **segment_columns):
    """A Segment "com Garrah, ontem Docker" holding two stored Corrections (Galo->Garrah, Doker->Docker)."""
    meeting = Meeting(title="Corrections", status=status, vocabulary="Vocabulary: Garrah, Docker")
    db_session.add(meeting)
    db_session.flush()
    text = "com Garrah, ontem Docker"
    segment = Segment(
        meeting_id=meeting.id, start_time=0.0, end_time=2.0, order=0,
        text=text, original_text=text,
        corrections=[
            {
                "start": 0.5, "end": 0.9, "heard": "Galo,", "term": "Garrah", "rule": "similar",
                "text_start": 4, "text_end": 10, "confirmed": False,
            },
            {
                "start": 1.5, "end": 1.9, "heard": "Doker", "term": "Docker", "rule": "similar",
                "text_start": 18, "text_end": 24, "confirmed": False,
            },
        ],
        **segment_columns,
    )
    db_session.add(segment)
    db_session.commit()
    return meeting, segment


def test_confirming_a_correction_teaches_its_misheard_form_and_marks_it_confirmed(db_session):
    meeting, segment = _meeting_with_corrections(db_session)
    client = TestClient(app)
    responses = []

    events = _events_caused_by(
        meeting.id,
        lambda: responses.append(
            client.post(f"/api/segments/{segment.id}/corrections/confirm", json={"start": 0.5})
        ),
    )

    (response,) = responses
    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "com Garrah, ontem Docker"
    assert [c["confirmed"] for c in body["corrections"]] == [True, False]
    entry = db_session.query(VocabularyEntry).filter_by(term="Garrah").one()
    assert entry.source_meeting_id == meeting.id
    assert entry.misheard_as == [{"form": "Galo", "count": 1, "confirmed": True}]
    assert events != []


def test_confirming_a_correction_confirms_a_form_learned_from_an_edit(db_session):
    _, segment = _meeting_with_corrections(db_session)
    entry = VocabularyEntry(
        term="Garrah", misheard_as=[{"form": "Galo", "count": 2, "confirmed": False}]
    )
    db_session.add(entry)
    db_session.commit()

    response = TestClient(app).post(
        f"/api/segments/{segment.id}/corrections/confirm", json={"start": 0.5}
    )

    assert response.status_code == 200
    db_session.refresh(entry)
    assert entry.misheard_as == [{"form": "Galo", "count": 3, "confirmed": True}]


def test_confirming_with_an_existing_term_adds_the_form_without_a_second_entry(db_session):
    _, segment = _meeting_with_corrections(db_session)
    db_session.add(VocabularyEntry(term="garrah", misheard_as=[{"form": "Garra", "count": 1}]))
    db_session.commit()

    response = TestClient(app).post(
        f"/api/segments/{segment.id}/corrections/confirm", json={"start": 0.5}
    )

    assert response.status_code == 200
    (entry,) = db_session.query(VocabularyEntry).all()
    assert entry.misheard_as == [
        {"form": "Garra", "count": 1},
        {"form": "Galo", "count": 1, "confirmed": True},
    ]


def test_confirming_twice_teaches_once(db_session):
    _, segment = _meeting_with_corrections(db_session)
    client = TestClient(app)

    for _ in range(2):
        assert client.post(
            f"/api/segments/{segment.id}/corrections/confirm", json={"start": 0.5}
        ).status_code == 200

    entry = db_session.query(VocabularyEntry).filter_by(term="Garrah").one()
    assert entry.misheard_as == [{"form": "Galo", "count": 1, "confirmed": True}]


def test_rejecting_a_correction_reverts_its_text_and_shifts_the_later_offsets(db_session):
    meeting, segment = _meeting_with_corrections(db_session)
    client = TestClient(app)
    responses = []

    events = _events_caused_by(
        meeting.id,
        lambda: responses.append(
            client.post(f"/api/segments/{segment.id}/corrections/reject", json={"start": 0.5})
        ),
    )

    (response,) = responses
    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "com Galo, ontem Docker"
    assert body["original_text"] == "com Galo, ontem Docker"
    assert body["is_edited"] is False
    assert body["corrections"] == [{
        "start": 1.5, "end": 1.9, "heard": "Doker", "term": "Docker", "rule": "similar",
        "text_start": 16, "text_end": 22, "confirmed": False,
    }]
    assert body["text"][16:22] == "Docker"
    assert events != []


def test_rejecting_records_one_rejected_form_across_meetings(db_session):
    first_meeting, first = _meeting_with_corrections(db_session)
    _, second = _meeting_with_corrections(db_session)
    client = TestClient(app)

    for segment in (first, second):
        assert client.post(
            f"/api/segments/{segment.id}/corrections/reject", json={"start": 0.5}
        ).status_code == 200

    (rejected,) = db_session.query(RejectedForm).all()
    assert (rejected.heard, rejected.term, rejected.source_meeting_id) == (
        "Galo", "Garrah", first_meeting.id
    )


def test_rejecting_removes_the_same_misheard_form_from_the_term(db_session):
    _, segment = _meeting_with_corrections(db_session)
    entry = VocabularyEntry(
        term="Garrah", misheard_as=[{"form": "galo", "count": 3}, {"form": "Garra", "count": 1}]
    )
    db_session.add(entry)
    db_session.commit()

    response = TestClient(app).post(
        f"/api/segments/{segment.id}/corrections/reject", json={"start": 0.5}
    )

    assert response.status_code == 200
    db_session.refresh(entry)
    assert entry.misheard_as == [{"form": "Garra", "count": 1}]


def test_rejecting_a_correction_stored_before_offsets_asks_to_reapply_vocabulary(db_session):
    _, segment = _meeting_with_corrections(db_session)
    segment.corrections = [
        {key: value for key, value in item.items() if key not in ("text_start", "text_end", "confirmed")}
        for item in segment.corrections
    ]
    db_session.commit()

    response = TestClient(app).post(
        f"/api/segments/{segment.id}/corrections/reject", json={"start": 0.5}
    )

    assert response.status_code == 409
    assert "reapply Vocabulary first" in response.json()["detail"]
    assert db_session.query(RejectedForm).count() == 0


def test_rejected_forms_are_listed_newest_first_and_can_be_removed(db_session):
    from datetime import datetime

    meeting, _ = _meeting_with_corrections(db_session)
    db_session.add_all([
        RejectedForm(
            heard="Galo", term="Garrah", source_meeting_id=meeting.id, created_at=datetime(2026, 1, 1)
        ),
        RejectedForm(heard="Doker", term="Docker", created_at=datetime(2026, 2, 1)),
    ])
    db_session.commit()
    client = TestClient(app)

    listed = client.get("/api/vocabulary/rejected-forms").json()

    assert [(item["heard"], item["term"], item["source_meeting_id"]) for item in listed] == [
        ("Doker", "Docker", None), ("Galo", "Garrah", meeting.id),
    ]
    assert set(listed[0]) == {"id", "heard", "term", "source_meeting_id", "created_at"}

    assert client.delete(f"/api/vocabulary/rejected-forms/{listed[0]['id']}").status_code == 200
    assert [item["heard"] for item in client.get("/api/vocabulary/rejected-forms").json()] == ["Galo"]
    assert client.delete(f"/api/vocabulary/rejected-forms/{listed[0]['id']}").status_code == 404


@pytest.mark.parametrize("action", ["confirm", "reject"])
def test_a_correction_action_is_refused_for_an_edited_segment_an_unknown_start_or_a_busy_meeting(
    db_session, action
):
    _, edited = _meeting_with_corrections(db_session, is_edited=True)
    _, plain = _meeting_with_corrections(db_session)
    _, busy = _meeting_with_corrections(db_session, status=MeetingStatus.PROCESSING)
    client = TestClient(app)

    def post(segment, start=0.5):
        return client.post(f"/api/segments/{segment.id}/corrections/{action}", json={"start": start})

    assert post(edited).status_code == 409
    assert post(plain, start=0.7).status_code == 409
    assert post(busy).status_code == 409
    assert client.post(
        f"/api/segments/nobody/corrections/{action}", json={"start": 0.5}
    ).status_code == 404
    assert db_session.query(VocabularyEntry).count() == 0
