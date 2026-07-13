import logging
from datetime import datetime

log = logging.getLogger(__name__)

from celery.exceptions import SoftTimeLimitExceeded

from .celery_app import celery_app
from .shared import update_progress, align_segments, publish_event
from database import SessionLocal
from models import Meeting, Speaker, Segment, Job, MeetingStatus
from models.job import JobStatus
from services.audio_service import AudioService
from services.whisper_service import WhisperService
from services.diarization_service import DiarizationService
from services.speaker_id_service import SpeakerIdService


@celery_app.task(bind=True)
def process_meeting_task(self, meeting_id: str, job_id: str):
    """Main pipeline: audio extraction -> transcription -> diarization -> alignment -> speaker naming."""
    db = SessionLocal()

    try:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        job = db.query(Job).filter(Job.id == job_id).first()

        if not meeting or not job:
            return {"error": "Meeting or Job not found"}

        job.status = JobStatus.RUNNING
        job.started_at = datetime.utcnow()
        meeting.status = MeetingStatus.PROCESSING

        # Clean up previous results for reprocessing
        db.query(Segment).filter(Segment.meeting_id == meeting_id).delete()
        db.query(Speaker).filter(Speaker.meeting_id == meeting_id).delete()
        db.commit()

        audio_service = AudioService()
        whisper_service = WhisperService()
        diarization_service = DiarizationService()
        speaker_id_service = SpeakerIdService()

        # Step 1: Extract audio
        update_progress(db, job, meeting, 2, "Extracting audio...")
        audio_path = audio_service.extract_audio(
            meeting.audio_filepath, meeting.id
        )
        duration = audio_service.get_duration(audio_path)
        meeting.duration = duration
        meeting.audio_filepath = audio_path
        db.commit()
        update_progress(db, job, meeting, 5, "Audio extracted")

        # Step 2: Transcription
        update_progress(db, job, meeting, 10, "Transcribing with Whisper...")
        whisper_segments = whisper_service.transcribe(audio_path, vocabulary=meeting.vocabulary)
        meeting.raw_transcription = whisper_segments
        db.commit()
        update_progress(db, job, meeting, 45, "Transcription complete")

        # Step 3: Diarization
        update_progress(db, job, meeting, 50, "Identifying speakers (diarization)...")
        diarization_segments = diarization_service.diarize(
            audio_path,
            min_speakers=meeting.min_speakers,
            max_speakers=meeting.max_speakers,
        )
        meeting.raw_diarization = diarization_segments
        db.commit()
        update_progress(db, job, meeting, 70, "Diarization complete")

        # Step 4: Alignment
        update_progress(db, job, meeting, 75, "Synchronizing speakers with text...")
        aligned = align_segments(whisper_segments, diarization_segments)
        update_progress(db, job, meeting, 80, "Synchronization complete")

        # Step 5: Speaker naming (Participant N, overridden by voice profile matches)
        update_progress(db, job, meeting, 85, "Matching against saved voice profiles...")
        speaker_labels = list(set(s["speaker"] for s in aligned if s["speaker"] != "UNKNOWN"))
        speaker_info = speaker_id_service.name_speakers(
            db, speaker_labels, diarization_segments, audio_path
        )

        update_progress(db, job, meeting, 90, "Saving results...")

        # Create speakers in DB
        speaker_map = {}  # label -> Speaker
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

        # Handle UNKNOWN speaker
        if any(s["speaker"] == "UNKNOWN" for s in aligned):
            unknown_speaker = Speaker(
                meeting_id=meeting.id,
                label="UNKNOWN",
                display_name="Unknown",
                color="#9ca3af",
            )
            db.add(unknown_speaker)
            db.flush()
            speaker_map["UNKNOWN"] = unknown_speaker

        # Create segments in DB
        for i, seg in enumerate(aligned):
            speaker = speaker_map.get(seg["speaker"])
            segment = Segment(
                meeting_id=meeting.id,
                speaker_id=speaker.id if speaker else None,
                start_time=seg["start"],
                end_time=seg["end"],
                text=seg["text"],
                original_text=seg["text"],
                order=i,
                confidence=seg.get("confidence"),
            )
            db.add(segment)

        # Update speaker stats
        for speaker in speaker_map.values():
            segs = [s for s in aligned if s["speaker"] == speaker.label]
            speaker.segment_count = len(segs)
            speaker.total_speaking_time = sum(s["end"] - s["start"] for s in segs)

        # Mark complete
        meeting.status = MeetingStatus.COMPLETED
        job.status = JobStatus.COMPLETED
        job.progress = 100
        job.current_step = "Done!"
        job.completed_at = datetime.utcnow()
        db.commit()

        update_progress(db, job, meeting, 100, "Done!")

        return {"status": "completed", "meeting_id": meeting_id}

    except SoftTimeLimitExceeded:
        db.rollback()
        error_msg = "Task exceeded time limit (55 minutes). Try a shorter recording."
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
        return {"error": error_msg}

    except Exception as e:
        import traceback
        log.error(f"process_meeting_task failed: {e}\n{traceback.format_exc()}")
        db.rollback()
        job = db.query(Job).filter(Job.id == job_id).first()
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if job:
            job.status = JobStatus.FAILED
            job.error = str(e)
            job.completed_at = datetime.utcnow()
        if meeting:
            meeting.status = MeetingStatus.FAILED
        db.commit()

        # Publish error
        try:
            publish_event(meeting_id, {"type": "error", "error": str(e)})
        except Exception:
            pass

        return {"error": str(e)}

    finally:
        db.close()
