import logging
from datetime import datetime

from .celery_app import celery_app
from .shared import publish_event
from database import SessionLocal
from models import Meeting, Segment, Speaker, MeetingInsight, InsightType
from models.job import Job, JobStatus
from services.llm_service import LLMService
from model_config import get_model_config

log = logging.getLogger(__name__)

MAX_TRANSCRIPT_CHARS = 15000

EXTRACTION_PROMPT = """You are a meeting analyst. Analyze the transcription and extract:

1. **Decisions** - Concrete decisions made during the meeting
2. **Action Items** - Tasks to be performed, with the responsible person if specified
3. **Open Questions** - Questions discussed but not answered or resolved

Respond ONLY with JSON in this format:
{
  "decisions": [
    {"content": "Description of the decision", "timestamp": 123.4}
  ],
  "action_items": [
    {"content": "What needs to be done", "assignee": "Person name or null", "timestamp": 234.5}
  ],
  "open_questions": [
    {"content": "Question that is unresolved", "timestamp": 345.6}
  ]
}

Timestamps should be in seconds from start, matching the nearest timestamp in the transcription.
If you find none for a category, return an empty list.
Write in English. Respond ONLY with JSON."""


@celery_app.task(bind=True, time_limit=180)
def extract_insights_task(self, meeting_id: str, job_id: str):
    """Extract decisions, action items, and open questions from a meeting transcript."""
    db = SessionLocal()

    try:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        job = db.query(Job).filter(Job.id == job_id).first()
        if not meeting or not job:
            return {"error": "Meeting or Job not found"}

        job.status = JobStatus.RUNNING
        job.started_at = datetime.utcnow()
        db.commit()

        # Build transcript
        segments = (
            db.query(Segment)
            .filter(Segment.meeting_id == meeting_id)
            .order_by(Segment.order)
            .all()
        )
        if not segments:
            raise ValueError("No transcript segments found")

        speakers = db.query(Speaker).filter(Speaker.meeting_id == meeting_id).all()
        speaker_map = {s.id: s.display_name or s.label for s in speakers}

        lines = []
        for seg in segments:
            speaker = speaker_map.get(seg.speaker_id, "Unknown") if seg.speaker_id else "Unknown"
            ts = f"{int(seg.start_time // 60)}:{int(seg.start_time % 60):02d}"
            lines.append(f"[{ts}] [{speaker}]: {seg.text}")

        transcript_text = "\n".join(lines)
        if len(transcript_text) > MAX_TRANSCRIPT_CHARS:
            transcript_text = transcript_text[:MAX_TRANSCRIPT_CHARS] + "\n\n[...transcription truncated...]"

        # Call LLM
        preset = get_model_config().get_model_for_task("actions")
        llm = LLMService(preset=preset)
        messages = [
            {"role": "system", "content": EXTRACTION_PROMPT},
            {"role": "user", "content": f"Meeting title: {meeting.title}\n\nTranscription:\n{transcript_text}"},
        ]

        response = llm._call(messages, max_tokens=4000)
        data = llm._parse_json(response)

        # Clear previous insights for this meeting
        db.query(MeetingInsight).filter(MeetingInsight.meeting_id == meeting_id).delete()

        order = 0
        for decision in data.get("decisions", []):
            db.add(MeetingInsight(
                meeting_id=meeting_id,
                insight_type=InsightType.DECISION,
                content=decision.get("content", ""),
                source_start_time=decision.get("timestamp"),
                order=order,
            ))
            order += 1

        for item in data.get("action_items", []):
            db.add(MeetingInsight(
                meeting_id=meeting_id,
                insight_type=InsightType.ACTION_ITEM,
                content=item.get("content", ""),
                assignee=item.get("assignee"),
                source_start_time=item.get("timestamp"),
                order=order,
            ))
            order += 1

        for question in data.get("open_questions", []):
            db.add(MeetingInsight(
                meeting_id=meeting_id,
                insight_type=InsightType.OPEN_QUESTION,
                content=question.get("content", ""),
                source_start_time=question.get("timestamp"),
                order=order,
            ))
            order += 1

        job.status = JobStatus.COMPLETED
        job.progress = 100
        job.current_step = "Done!"
        job.completed_at = datetime.utcnow()
        db.commit()

        publish_event(meeting_id, {
            "type": "insights_completed",
            "count": order,
        })

        log.info(f"Extracted {order} insights from meeting {meeting_id}")
        return {"status": "completed", "count": order}

    except Exception as e:
        db.rollback()
        log.error(f"Insights extraction failed: {e}")
        try:
            job = db.query(Job).filter(Job.id == job_id).first()
            if job:
                job.status = JobStatus.FAILED
                job.error = str(e)
                job.completed_at = datetime.utcnow()
                db.commit()
        except Exception:
            pass
        return {"error": str(e)}

    finally:
        db.close()
