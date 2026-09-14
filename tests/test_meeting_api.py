import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
from main import app
from models import Meeting, MeetingStatus
from models.job import Job


class FakeHealth:
    def to_dict(self):
        return {
            "state": "blocked", "summary": "runtime mismatch", "checks": [],
            "fingerprint": "fixture", "available": False, "reason": "runtime mismatch",
        }


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

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
    monkeypatch.setattr("api.meetings.process_meeting_task.delay", lambda *_args: queued.append(True))

    response = client.post(f"/api/meetings/{meeting_id}/process")

    assert response.status_code == 409
    assert response.json()["detail"]["health"]["state"] == "blocked"
    db_session.refresh(meeting)
    assert meeting.status == MeetingStatus.UPLOADED
    assert db_session.query(Job).count() == 0
    assert queued == []
