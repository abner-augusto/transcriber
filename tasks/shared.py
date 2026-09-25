from contextlib import contextmanager
from datetime import datetime
import json
import logging

import redis
from celery.exceptions import SoftTimeLimitExceeded

from config import settings
from database import SessionLocal
from models import Job, Meeting, MeetingStatus, Speaker, Segment
from models.job import JobStatus
from run_config import resolve_run_config

log = logging.getLogger(__name__)

# Module-level Redis connection pool (reused across all publish calls)
_redis_pool = redis.ConnectionPool.from_url(settings.redis_url)


class MeetingNotFoundError(Exception):
    """Raised when a meeting or job cannot be found."""


@contextmanager
def meeting_job(meeting_id: str, job_id: str):
    """Context manager for meeting job lifecycle.

    Opens a DB session, loads the meeting and job, transitions to RUNNING,
    yields (db, meeting, job), then handles success (COMPLETED) or failure
    (FAILED + Redis error event).
    """
    db = SessionLocal()
    try:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        job = db.query(Job).filter(Job.id == job_id).first()
        if not meeting or not job:
            raise MeetingNotFoundError("Meeting or Job not found")

        job.run_config = resolve_run_config(meeting).model_dump(mode="json", exclude_none=True)
        job.status = JobStatus.RUNNING
        job.started_at = datetime.utcnow()
        meeting.status = MeetingStatus.PROCESSING
        db.commit()

        yield db, meeting, job

        # Success path
        meeting.status = MeetingStatus.COMPLETED
        job.status = JobStatus.COMPLETED
        job.progress = 100
        job.current_step = "Done!"
        job.completed_at = datetime.utcnow()
        db.commit()
        update_progress(db, job, meeting, 100, "Done!")

    except SoftTimeLimitExceeded:
        db.rollback()
        error_msg = "Task exceeded time limit (55 minutes). Try a shorter recording."
        _fail_job(db, meeting_id, job_id, error_msg)
        raise
    except Exception as e:
        db.rollback()
        _fail_job(db, meeting_id, job_id, str(e))
        raise
    finally:
        db.close()
        try:
            from engines.gpu_memory import unload_all_engines

            unload_all_engines()
        except Exception as exc:
            log.warning(f"[meeting_job] GPU cleanup failed: {exc}")


def _fail_job(db, meeting_id: str, job_id: str, error_msg: str):
    """Mark job and meeting as failed, publish error event."""
    job = db.query(Job).filter(Job.id == job_id).first()
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if job:
        job.status = JobStatus.FAILED
        job.error = error_msg
        job.completed_at = datetime.utcnow()
    if meeting:
        meeting.status = MeetingStatus.FAILED
    db.commit()
    try:
        publish_event(meeting_id, {"type": "error", "error": error_msg})
    except Exception:
        pass


def rebuild_speakers_and_segments(db, meeting, aligned, speaker_info, speaker_id_service):
    """Preserve edits, delete old data, create new speakers + segments."""
    EDIT_TIME_TOLERANCE = 1.5

    existing_segments = (
        db.query(Segment)
        .filter(Segment.meeting_id == meeting.id)
        .order_by(Segment.order)
        .all()
    )
    edited_segments = [
        {"start": s.start_time, "end": s.end_time, "text": s.text}
        for s in existing_segments if s.is_edited
    ]

    db.query(Segment).filter(Segment.meeting_id == meeting.id).delete()
    db.query(Speaker).filter(Speaker.meeting_id == meeting.id).delete()
    db.commit()

    speaker_map = {}
    for i, (label, info) in enumerate(sorted(speaker_info.items())):
        speaker = Speaker(
            meeting_id=meeting.id,
            label=label,
            display_name=info["name"],
            color=speaker_id_service.get_color(i),
            identified_by=info.get("identified_by"),
            confidence=info.get("confidence"),
        )
        db.add(speaker)
        db.flush()
        speaker_map[label] = speaker

    if any(s["speaker"] == "UNKNOWN" for s in aligned):
        unk = Speaker(
            meeting_id=meeting.id,
            label="UNKNOWN",
            display_name="Unknown",
            color="#9ca3af",
        )
        db.add(unk)
        db.flush()
        speaker_map["UNKNOWN"] = unk

    for i, seg in enumerate(aligned):
        speaker = speaker_map.get(seg["speaker"])
        text = seg["text"]
        is_edited = False

        for edited in edited_segments:
            if (abs(seg["start"] - edited["start"]) < EDIT_TIME_TOLERANCE
                    and abs(seg["end"] - edited["end"]) < EDIT_TIME_TOLERANCE):
                text = edited["text"]
                is_edited = True
                break

        segment = Segment(
            meeting_id=meeting.id,
            speaker_id=speaker.id if speaker else None,
            start_time=seg["start"],
            end_time=seg["end"],
            text=text,
            original_text=seg["text"],
            order=i,
            is_edited=is_edited,
            confidence=seg.get("confidence"),
            corrections=[] if is_edited else seg.get("corrections", []),
        )
        db.add(segment)

    for spk in speaker_map.values():
        segs = [s for s in aligned if s["speaker"] == spk.label]
        spk.segment_count = len(segs)
        spk.total_speaking_time = sum(s["end"] - s["start"] for s in segs)

    db.commit()


def update_progress(db, job: Job, meeting: Meeting, progress: float, step: str):
    """Update job progress and broadcast via Redis pub/sub."""
    job.progress = progress
    job.current_step = step
    db.commit()

    publish_event(meeting.id, {
        "type": "progress",
        "progress": progress,
        "step": step,
        "status": meeting.status.value,
    })


def publish_event(meeting_id: str, data: dict):
    """Publish an event to Redis pub/sub for a meeting."""
    r = redis.Redis(connection_pool=_redis_pool)
    r.publish(f"meeting:{meeting_id}", json.dumps(data))
