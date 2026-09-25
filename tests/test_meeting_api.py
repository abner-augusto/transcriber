import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
import jobs
from jobs.runners import InProcessBus, InlineJobRunner
from main import app
from models import Meeting, MeetingStatus, Segment, VocabularyEntry
from models.job import Job, JobType


class FakeHealth:
    def to_dict(self):
        return {
            "state": "blocked", "summary": "runtime mismatch", "checks": [],
            "fingerprint": "fixture", "available": False, "reason": "runtime mismatch",
        }


@pytest.fixture
def db_session(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    runner = InlineJobRunner(handlers={})
    bus = InProcessBus()
    previous = jobs.configure(
        runner=runner, progress_bus=bus, session_factory=TestingSessionLocal
    )
    app.state.test_job_runner = runner
    app.state.test_progress_bus = bus

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        app.dependency_overrides.clear()
        jobs.configure(**previous)
        del app.state.test_job_runner
        del app.state.test_progress_bus


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
    assert duplicate.status_code == 400
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

    assert response.status_code == 400
    assert response.json()["detail"] == "Already processing"
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


def test_health_checks_progress_adapter(monkeypatch, tmp_path):
    import main

    monkeypatch.setattr(main._settings, "storage_path", str(tmp_path))
    calls = []
    monkeypatch.setattr(jobs, "check_progress_bus", lambda: calls.append(True))

    response = main.health()

    assert response["progress_bus"] == "ok"
    assert calls == [True]

def test_segment_edits_learn_and_increment_misheard_form(db_session):
    meeting = Meeting(title="Learning", status=MeetingStatus.COMPLETED)
    entry = VocabularyEntry(term="Garrah")
    db_session.add_all([meeting, entry])
    db_session.flush()
    segment = Segment(
        meeting_id=meeting.id, start_time=0, end_time=0.5,
        text="Galo", original_text="Galo", order=0,
    )
    db_session.add(segment)
    db_session.commit()

    client = TestClient(app)
    for _ in range(2):
        response = client.put(f"/api/segments/{segment.id}", json={"text": "Garrah"})
        assert response.status_code == 200
        assert response.json()["text"] == "Garrah"

    db_session.refresh(entry)
    assert entry.misheard_as == [{"form": "Galo", "count": 2}]
