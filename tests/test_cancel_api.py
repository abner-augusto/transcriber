"""POST /api/meetings/{id}/cancel and `transcriber_cli cancel` (plan 048)."""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

import jobs
from main import app
from models import Meeting, MeetingStatus
from models.job import Job, JobStatus, JobType
from transcriber_cli.client import Api
from transcriber_cli.main import main

from .test_transcriber_cli import forward_to_app, run


def _meeting(db, status=MeetingStatus.PROCESSING, title="Cancel me"):
    meeting = Meeting(title=title, status=status)
    db.add(meeting)
    db.commit()
    return meeting


def _job(db, meeting, status, created_at=None):
    job = Job(
        meeting_id=meeting.id, job_type=JobType.PROCESS_MEETING, status=status,
        created_at=created_at or datetime.utcnow(),
    )
    db.add(job)
    db.commit()
    return job


@pytest.mark.parametrize("status", [JobStatus.PENDING, JobStatus.RUNNING])
def test_cancel_records_the_request_and_changes_no_status(db_session, status):
    meeting = _meeting(db_session)
    job = _job(db_session, meeting, status)

    response = TestClient(app).post(f"/api/meetings/{meeting.id}/cancel")

    assert response.status_code == 200
    body = response.json()
    assert (body["id"], body["status"]) == (job.id, status.value)
    assert body["cancel_requested_at"] is not None
    db_session.refresh(job)
    db_session.refresh(meeting)
    assert job.cancel_requested_at is not None
    assert (job.status, meeting.status) == (status, MeetingStatus.PROCESSING)  # the runner's loop moves them


def test_cancelling_twice_returns_the_same_request(db_session):
    meeting = _meeting(db_session)
    job = _job(db_session, meeting, JobStatus.RUNNING)
    client = TestClient(app)

    first = client.post(f"/api/meetings/{meeting.id}/cancel").json()
    second = client.post(f"/api/meetings/{meeting.id}/cancel")

    assert second.status_code == 200
    assert second.json()["cancel_requested_at"] == first["cancel_requested_at"]
    assert second.json()["id"] == job.id


def test_cancel_names_the_newest_unfinished_job_only(db_session):
    meeting = _meeting(db_session, MeetingStatus.COMPLETED)
    _job(db_session, meeting, JobStatus.COMPLETED, datetime(2026, 1, 1))
    running = _job(db_session, meeting, JobStatus.RUNNING, datetime(2026, 1, 2))
    other = _meeting(db_session, title="Other")
    other_job = _job(db_session, other, JobStatus.RUNNING)

    TestClient(app).post(f"/api/meetings/{meeting.id}/cancel")

    db_session.refresh(running)
    db_session.refresh(other_job)
    assert running.cancel_requested_at is not None
    assert other_job.cancel_requested_at is None


def test_cancel_with_nothing_running_is_a_conflict(db_session):
    meeting = _meeting(db_session, MeetingStatus.COMPLETED)
    _job(db_session, meeting, JobStatus.COMPLETED)

    response = TestClient(app).post(f"/api/meetings/{meeting.id}/cancel")

    assert response.status_code == 409
    assert "no Job to cancel" in response.json()["detail"]


def test_cancel_of_a_missing_meeting_is_not_found(db_session):
    assert TestClient(app).post("/api/meetings/nope/cancel").status_code == 404


def test_cancel_that_loses_to_the_end_of_the_job_is_a_conflict(db_session, monkeypatch):
    meeting = _meeting(db_session)
    _job(db_session, meeting, JobStatus.RUNNING)
    # The Job finished between the lookup and the request: the runner records nothing.
    monkeypatch.setattr(app.state.test_job_runner, "cancel", lambda job_id: None)

    response = TestClient(app).post(f"/api/meetings/{meeting.id}/cancel")

    assert response.status_code == 409


# --- the CLI ---------------------------------------------------------------------------


def _runner_finishes_the_cancel(db_session, client):
    """What the runner's loop does a moment after the request, done on the POST."""
    forward = forward_to_app(client)

    def transport(method, url, headers, body):
        status, content = forward(method, url, headers, body)
        if method == "POST" and url.endswith("/cancel"):
            import json
            assert jobs.finish_cancel(json.loads(content)["id"])
        return status, content

    return Api(base_url="http://test", transport=transport)


def test_cli_cancel_waits_for_the_runner_and_says_where_the_meeting_went(db_session, capsys):
    meeting = _meeting(db_session)
    _job(db_session, meeting, JobStatus.RUNNING)
    api = _runner_finishes_the_cancel(db_session, TestClient(app))

    code, out, _ = run(["cancel", meeting.id, "--wait", "--interval", "0"], api, capsys)

    assert code == 0
    assert "cancelled" in out and "uploaded" in out
    db_session.refresh(meeting)
    assert meeting.status == MeetingStatus.UPLOADED


def test_cli_cancel_returns_after_the_request_unless_asked_to_wait(db_session, capsys):
    meeting = _meeting(db_session)
    job = _job(db_session, meeting, JobStatus.RUNNING)
    api = Api(base_url="http://test", transport=forward_to_app(TestClient(app)))

    code, out, _ = run(["cancel", meeting.id], api, capsys)

    assert code == 0
    assert job.id[:8] in out
    db_session.refresh(job)
    assert job.cancel_requested_at is not None and job.status == JobStatus.RUNNING


def test_cli_cancel_times_out_with_exit_3_when_the_runner_does_not_answer(db_session, capsys):
    meeting = _meeting(db_session)
    _job(db_session, meeting, JobStatus.RUNNING)
    api = Api(base_url="http://test", transport=forward_to_app(TestClient(app)))

    code, _, err = run(["cancel", meeting.id, "--wait", "--interval", "0", "--timeout", "0"], api, capsys)

    assert code == 3
    assert "still running" in err


def test_cli_cancel_with_nothing_to_cancel_exits_1(db_session, capsys):
    meeting = _meeting(db_session, MeetingStatus.COMPLETED)
    api = Api(base_url="http://test", transport=forward_to_app(TestClient(app)))

    code, _, err = run(["cancel", meeting.id], api, capsys)

    assert code == 1
    assert err.startswith("error: ")


def test_wait_reports_a_cancelled_job_instead_of_polling_forever(db_session, capsys):
    meeting = _meeting(db_session, MeetingStatus.UPLOADED)
    _job(db_session, meeting, JobStatus.CANCELLED)
    api = Api(base_url="http://test", transport=forward_to_app(TestClient(app)))

    code, out, _ = run(["wait", meeting.id, "--interval", "0", "--timeout", "5"], api, capsys)

    assert code == 1
    assert "cancelled" in out
