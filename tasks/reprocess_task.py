from datetime import datetime

from .celery_app import celery_app
from .shared import (
    attribution_turns_from_stored,
    build_segments,
    exclusive_turns_from_stored,
    overlaps_from_stored,
    publish_event,
    turns_from_stored,
    update_progress,
    words_from_stored,
    prepare_diarization,
)
from database import SessionLocal
from engines import DIARIZER_ENGINE, make_diarizer
from models import Meeting, Speaker, Segment, Job, MeetingStatus
from models.job import JobStatus
from preferences import get_speaker_switch_penalty
from services.speaker_id_service import SpeakerIdService
from services.vad_service import VadService


@celery_app.task(bind=True)
def rediarize_task(self, meeting_id: str, job_id: str):
    """Re-run diarization without re-transcribing.

    Keeps the Meeting's existing Words, runs the Diarizer again for fresh Turns, and
    rebuilds the Segments from both. Preserves manually edited segment text.
    """
    db = SessionLocal()
    try:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        job = db.query(Job).filter(Job.id == job_id).first()
        if not meeting or not job:
            return {"error": "Meeting or Job not found"}

        job.status = JobStatus.RUNNING
        job.started_at = datetime.utcnow()
        meeting.status = MeetingStatus.PROCESSING
        db.commit()

        words = words_from_stored(meeting.raw_transcription)
        if not words:
            raise RuntimeError("No existing transcription found. Run full processing first.")

        audio_path = meeting.audio_filepath
        if not audio_path:
            raise RuntimeError("No audio file found.")

        diarizer = make_diarizer()
        speaker_id_service = SpeakerIdService()

        # Step 1: Fresh diarization & VAD bounding
        update_progress(db, job, meeting, 10, "Running new speaker identification...")
        diar_result = diarizer.diarize(
            audio_path,
            min_speakers=meeting.min_speakers,
            max_speakers=meeting.max_speakers,
        )
        vad_service = VadService()
        diarization_data, bounded_turns, bounded_exclusive_turns = prepare_diarization(
            diar_result, audio_path, vad_service
        )

        meeting.raw_diarization = {
            "engine": DIARIZER_ENGINE,
            **diarization_data,
        }
        db.commit()
        update_progress(db, job, meeting, 50, "Diarization complete")

        # Step 2: Rebuild the Segments from the old Words and the new Turns (using exclusive turns for attribution if present)
        update_progress(db, job, meeting, 55, "Synchronizing speakers with text...")
        attribution_turns = (
            bounded_exclusive_turns
            if (bounded_exclusive_turns is not None and len(bounded_exclusive_turns) > 0)
            else bounded_turns
        )
        aligned = build_segments(
            words,
            attribution_turns,
            switch_penalty=get_speaker_switch_penalty(),
        )

        # Step 3: Speaker naming (Participant N, overridden by voice profile matches)
        update_progress(db, job, meeting, 65, "Matching against saved voice profiles...")
        all_turns = bounded_turns + (bounded_exclusive_turns or [])
        speaker_labels = sorted({t.speaker for t in all_turns})
        speaker_info = speaker_id_service.name_speakers(
            db, speaker_labels, bounded_turns, audio_path
        )

        # Step 4: Collect edits, recreate speakers + segments
        update_progress(db, job, meeting, 85, "Saving results...")
        _rebuild_speakers_and_segments(db, meeting, aligned, speaker_info, speaker_id_service)

        meeting.status = MeetingStatus.COMPLETED
        job.status = JobStatus.COMPLETED
        job.progress = 100
        job.current_step = "Done!"
        job.completed_at = datetime.utcnow()
        db.commit()
        update_progress(db, job, meeting, 100, "Done!")
        return {"status": "completed", "meeting_id": meeting_id}

    except Exception as e:
        db.rollback()
        _fail_job(db, meeting_id, job_id, str(e))
        return {"error": str(e)}
    finally:
        db.close()


@celery_app.task(bind=True)
def reidentify_task(self, meeting_id: str, job_id: str):
    """Re-run speaker naming without re-transcribing or re-diarizing.

    Reuses the Meeting's existing Words and Turns and only re-names the Speakers against
    the saved Voice Profiles. This is how a newly-saved Voice Profile gets applied to an
    already-processed Meeting. Preserves edited text.
    """
    db = SessionLocal()
    try:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        job = db.query(Job).filter(Job.id == job_id).first()
        if not meeting or not job:
            return {"error": "Meeting or Job not found"}

        job.status = JobStatus.RUNNING
        job.started_at = datetime.utcnow()
        meeting.status = MeetingStatus.PROCESSING
        db.commit()

        words = words_from_stored(meeting.raw_transcription)
        turns = turns_from_stored(meeting.raw_diarization)
        attribution_turns = attribution_turns_from_stored(meeting.raw_diarization)
        if not words or not turns:
            raise RuntimeError("No existing transcription/diarization found. Run full processing first.")

        audio_path = meeting.audio_filepath
        if not audio_path:
            raise RuntimeError("No audio file found.")

        speaker_id_service = SpeakerIdService()

        # Step 1: Rebuild the Segments from the stored Words and attribution Turns
        update_progress(db, job, meeting, 20, "Synchronizing speakers with text...")
        aligned = build_segments(
            words,
            attribution_turns,
            switch_penalty=get_speaker_switch_penalty(),
        )

        # Step 2: Re-name speakers against the saved Voice Profiles
        update_progress(db, job, meeting, 40, "Matching against saved voice profiles...")
        exclusive_turns = exclusive_turns_from_stored(meeting.raw_diarization)
        all_turns = turns + (exclusive_turns or [])
        speaker_labels = sorted({t.speaker for t in all_turns})
        speaker_info = speaker_id_service.name_speakers(
            db, speaker_labels, turns, audio_path
        )

        # Step 3: Rebuild
        update_progress(db, job, meeting, 80, "Saving results...")
        _rebuild_speakers_and_segments(db, meeting, aligned, speaker_info, speaker_id_service)

        meeting.status = MeetingStatus.COMPLETED
        job.status = JobStatus.COMPLETED
        job.progress = 100
        job.current_step = "Done!"
        job.completed_at = datetime.utcnow()
        db.commit()
        update_progress(db, job, meeting, 100, "Done!")
        return {"status": "completed", "meeting_id": meeting_id}

    except Exception as e:
        db.rollback()
        _fail_job(db, meeting_id, job_id, str(e))
        return {"error": str(e)}
    finally:
        db.close()


def _rebuild_speakers_and_segments(db, meeting, aligned, speaker_info, speaker_id_service):
    """Shared logic: preserve edits, delete old data, create new speakers + segments."""
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
        )
        db.add(segment)

    for spk in speaker_map.values():
        segs = [s for s in aligned if s["speaker"] == spk.label]
        spk.segment_count = len(segs)
        spk.total_speaking_time = sum(s["end"] - s["start"] for s in segs)

    db.commit()


def _fail_job(db, meeting_id, job_id, error_msg):
    """Mark job and meeting as failed."""
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
