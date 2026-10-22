"""Status values are stored in the database and mirrored by the frontend types.

They also lock out the removed live-recording states: bringing one back is a
deliberate change to these sets. CANCELLED came back on purpose with plan 048
(ticket 09), which gave it a producer.
"""

from pathlib import Path

from models import MeetingStatus
from models.job import JobStatus


ROOT = Path(__file__).resolve().parent.parent

ALLOWED_MEETING_STATUSES = {"uploaded", "processing", "completed", "failed"}
ALLOWED_JOB_STATUSES = {"pending", "running", "completed", "failed", "cancelled"}


def test_meeting_status_enum_has_no_live_or_upload_placeholders():
    assert {status.value for status in MeetingStatus} == ALLOWED_MEETING_STATUSES
    assert not hasattr(MeetingStatus, "UPLOADING")


def test_job_status_enum_is_the_allowed_set():
    assert {status.value for status in JobStatus} == ALLOWED_JOB_STATUSES


def test_frontend_meeting_type_matches_backend_statuses():
    types = (ROOT / "frontend" / "src" / "types.ts").read_text(encoding="utf-8")
    meeting_block = types.split("export interface Meeting")[1].split("export interface Speaker")[0]

    assert 'status: "uploaded" | "processing" | "completed" | "failed"' in meeting_block
    assert "recording_status" not in meeting_block
    assert "mode:" not in meeting_block
