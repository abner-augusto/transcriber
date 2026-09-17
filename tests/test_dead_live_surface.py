"""Regression lock for the removed live-recording / live-session surface."""

from pathlib import Path

from models import Meeting, MeetingStatus
from models.job import JobStatus


ROOT = Path(__file__).resolve().parent.parent

ALLOWED_MEETING_STATUSES = {"uploaded", "processing", "completed", "failed"}
ALLOWED_JOB_STATUSES = {"pending", "running", "completed", "failed"}


def test_meeting_status_enum_has_no_live_or_upload_placeholders():
    assert {status.value for status in MeetingStatus} == ALLOWED_MEETING_STATUSES
    assert not hasattr(MeetingStatus, "UPLOADING")


def test_job_status_enum_has_no_cancelled():
    assert {status.value for status in JobStatus} == ALLOWED_JOB_STATUSES
    assert not hasattr(JobStatus, "CANCELLED")


def test_meeting_dict_omits_live_session_fields():
    meeting = Meeting(title="No live fields", status=MeetingStatus.UPLOADED)
    payload = meeting.to_dict()

    assert payload["status"] in ALLOWED_MEETING_STATUSES
    assert "mode" not in payload
    assert "recording_status" not in payload


def test_app_exposes_no_live_routes():
    from main import app

    paths = [getattr(route, "path", "") for route in app.routes]
    live_paths = [path for path in paths if "/live" in path]
    assert live_paths == []


def test_frontend_meeting_type_matches_backend_statuses():
    types = (ROOT / "frontend" / "src" / "types.ts").read_text(encoding="utf-8")
    meeting_block = types.split("export interface Meeting")[1].split("export interface Speaker")[0]

    assert 'status: "uploaded" | "processing" | "completed" | "failed"' in meeting_block
    assert "recording_status" not in meeting_block
    assert "mode:" not in meeting_block


def test_frontend_has_no_live_session_branches():
    homepage = (ROOT / "frontend" / "src" / "pages" / "HomePage.tsx").read_text(encoding="utf-8")
    meeting_page = (ROOT / "frontend" / "src" / "pages" / "MeetingPage.tsx").read_text(encoding="utf-8")
    transcript = (ROOT / "frontend" / "src" / "components" / "TranscriptView.tsx").read_text(
        encoding="utf-8"
    )

    assert "recording:" not in homepage
    assert "finalizing:" not in homepage
    assert 'mode === "live"' not in homepage
    assert "finalizing" not in meeting_page
    assert "isLive" not in transcript
