import logging
from datetime import datetime

log = logging.getLogger(__name__)

from celery.exceptions import SoftTimeLimitExceeded

from .celery_app import celery_app
from .shared import update_progress, build_segments, publish_event, compute_overlaps
from database import SessionLocal
from engines import DIARIZER_ENGINE, DiarizationResult, Turn, make_diarizer, make_transcriber
from models import Meeting, Speaker, Segment, Job, MeetingStatus
from models.job import JobStatus
from presets import resolve_preset
from services.audio_service import AudioService
from services.speaker_id_service import SpeakerIdService
from services.vad_service import VadService


@celery_app.task(bind=True)
def process_meeting_task(self, meeting_id: str, job_id: str):
    """Main pipeline: audio extraction -> transcription -> diarization -> segments -> speaker naming."""
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
        speaker_id_service = SpeakerIdService()

        preset = resolve_preset(meeting.preset_id)
        transcriber = make_transcriber(preset)
        diarizer = make_diarizer()

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
        update_progress(db, job, meeting, 10, f"Transcribing with {preset['name']}...")
        words = transcriber.transcribe(audio_path, vocabulary=meeting.vocabulary)

        # Optional Step 2.5: Higher-precision CTC Forced Alignment
        from preferences import load_preferences
        prefs = load_preferences()
        fa_pref = prefs.get("forced_alignment", {})
        fa_enabled = bool(
            preset.get("forced_alignment")
            or (isinstance(fa_pref, dict) and fa_pref.get("enabled"))
            or (isinstance(fa_pref, bool) and fa_pref)
        )
        if fa_enabled:
            update_progress(db, job, meeting, 46, "Refining word timestamps (CTC alignment)...")
            from engines import align_words
            fa_config = fa_pref if isinstance(fa_pref, dict) else {}
            words = align_words(audio_path, words, config=fa_config)

        raw_transcription_data = {
            "engine": preset["engine"],
            "preset": preset["id"],
            "words": [w.to_dict() for w in words],
        }
        if hasattr(transcriber, "resolve_dtw_preset"):
            resolved_dtw = transcriber.resolve_dtw_preset()
            raw_transcription_data["dtw"] = resolved_dtw if (getattr(transcriber, "dtw_enabled", False) and resolved_dtw) else False

        meeting.raw_transcription = raw_transcription_data
        db.commit()
        update_progress(db, job, meeting, 48 if fa_enabled else 45, "Transcription complete")


        # Step 3: Diarization & VAD bounding
        update_progress(db, job, meeting, 50, "Identifying speakers (diarization)...")
        diar_result = diarizer.diarize(
            audio_path,
            min_speakers=meeting.min_speakers,
            max_speakers=meeting.max_speakers,
        )
        if isinstance(diar_result, DiarizationResult):
            raw_turns = diar_result.turns
            raw_exclusive_turns = diar_result.exclusive_turns
        elif isinstance(diar_result, dict):
            raw_turns = [Turn.from_dict(t) for t in diar_result.get("turns", [])]
            raw_exclusive_turns = (
                [Turn.from_dict(t) for t in diar_result["exclusive_turns"]]
                if diar_result.get("exclusive_turns") is not None
                else None
            )
        else:
            raw_turns = list(diar_result)
            raw_exclusive_turns = None

        vad_service = VadService()
        vad_segments = vad_service.compute_vad_segments(audio_path)
        bounded_turns = vad_service.mask_turns_to_vad(raw_turns, vad_segments)
        bounded_exclusive_turns = (
            vad_service.mask_turns_to_vad(raw_exclusive_turns, vad_segments)
            if raw_exclusive_turns is not None
            else None
        )
        overlaps = compute_overlaps(bounded_turns)

        meeting.raw_diarization = {
            "engine": DIARIZER_ENGINE,
            "turns": [t.to_dict() for t in bounded_turns],
            "exclusive_turns": (
                [t.to_dict() for t in bounded_exclusive_turns]
                if bounded_exclusive_turns is not None
                else None
            ),
            "overlaps": overlaps,
        }
        db.commit()
        update_progress(db, job, meeting, 70, "Diarization complete")

        # Step 4: Build the Segments a reader sees, from the Words and the Turns
        # When exclusive diarization is available, attribute from exclusive turns
        update_progress(db, job, meeting, 75, "Synchronizing speakers with text...")
        attribution_turns = (
            bounded_exclusive_turns
            if (bounded_exclusive_turns is not None and len(bounded_exclusive_turns) > 0)
            else bounded_turns
        )
        aligned = build_segments(words, attribution_turns)
        update_progress(db, job, meeting, 80, "Synchronization complete")

        # Step 5: Speaker naming (Participant N, overridden by voice profile matches)
        update_progress(db, job, meeting, 85, "Matching against saved voice profiles...")
        all_turns = bounded_turns + (bounded_exclusive_turns or [])
        speaker_labels = sorted({t.speaker for t in all_turns})
        speaker_info = speaker_id_service.name_speakers(
            db, speaker_labels, bounded_turns, audio_path
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
