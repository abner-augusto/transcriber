from .celery_app import celery_app
from .diarization import diarize_meeting
from .shared import (
    MeetingNotFoundError,
    meeting_job,
    update_progress,
    rebuild_speakers_and_segments,
)
from engines import make_diarizer
from preferences import get_speaker_switch_penalty
from services.speaker_id_service import SpeakerIdService
from services.vad_service import VadService
from transcript.diarization import MeetingDiarization
from transcript.segments import derive_segments
from transcript.words import words_from_stored
from .vocabulary import vocabulary_correction_for_meeting
from models import Speaker, Segment


def _reprocess_meeting(db, meeting, job, rerun_diarization: bool):
    """Shared execution logic for re-diarization and re-identification.

    When rerun_diarization is True, runs the Diarization stage again for fresh Turns —
    always through the Diarizer, never a Transcriber's native Turns.
    When False, reuses the Meeting's existing Turns and only re-names Speakers.
    """
    words = words_from_stored(meeting.raw_transcription)
    if not words:
        raise RuntimeError("No existing transcription found. Run full processing first.")

    audio_path = meeting.audio_filepath
    if not audio_path:
        raise RuntimeError("No audio file found.")

    speaker_id_service = SpeakerIdService()

    if rerun_diarization:
        diarizer = make_diarizer()
        update_progress(db, job, meeting, 10, "Running new speaker identification...")
        diarization = diarize_meeting(meeting, audio_path, diarizer=diarizer, vad_service=VadService())
        meeting.raw_diarization = diarization.to_stored()
        db.commit()
        update_progress(db, job, meeting, 50, "Diarization complete")
        if hasattr(diarizer, "unload"):
            diarizer.unload()
        from engines.gpu_memory import release_gpu_memory
        release_gpu_memory()
    else:
        diarization = MeetingDiarization.from_stored(meeting.raw_diarization)
        if diarization is None or not diarization.turns:
            raise RuntimeError("No existing diarization found. Run full processing first.")

    update_progress(
        db, job, meeting,
        55 if rerun_diarization else 20,
        "Synchronizing speakers with text...",
    )
    correction = vocabulary_correction_for_meeting(db, meeting)
    aligned = derive_segments(
        words, diarization, switch_penalty=get_speaker_switch_penalty(), correction=correction
    )

    # Speaker naming (Participant N, overridden by voice profile matches)
    update_progress(
        db, job, meeting,
        65 if rerun_diarization else 40,
        "Matching against saved voice profiles...",
    )
    speaker_info = speaker_id_service.name_speakers(
        db,
        diarization.speaker_labels,
        diarization.turns,
        audio_path,
        host_label=diarization.host_label,
    )
    if hasattr(speaker_id_service, "unload"):
        speaker_id_service.unload()
    from engines.gpu_memory import release_gpu_memory
    release_gpu_memory()

    # Rebuild speakers and segments (preserving edits)
    update_progress(
        db, job, meeting,
        85 if rerun_diarization else 80,
        "Saving results...",
    )
    rebuild_speakers_and_segments(db, meeting, aligned, speaker_info, speaker_id_service)


@celery_app.task(bind=True)
def rediarize_task(self, meeting_id: str, job_id: str):
    """Re-run diarization without re-transcribing.

    Keeps the Meeting's existing Words, runs the Diarizer again for fresh Turns, and
    rebuilds the Segments from both. Preserves manually edited segment text.
    """
    try:
        with meeting_job(meeting_id, job_id) as (db, meeting, job):
            _reprocess_meeting(db, meeting, job, rerun_diarization=True)
        return {"status": "completed", "meeting_id": meeting_id}
    except MeetingNotFoundError:
        return {"error": "Meeting or Job not found"}


@celery_app.task(bind=True)
def reidentify_task(self, meeting_id: str, job_id: str):
    """Re-run speaker naming without re-transcribing or re-diarizing.

    Reuses the Meeting's existing Words and Turns and only re-names the Speakers against
    the saved Voice Profiles. This is how a newly-saved Voice Profile gets applied to an
    already-processed Meeting. Preserves edited text.
    """
    try:
        with meeting_job(meeting_id, job_id) as (db, meeting, job):
            _reprocess_meeting(db, meeting, job, rerun_diarization=False)
        return {"status": "completed", "meeting_id": meeting_id}
    except MeetingNotFoundError:
        return {"error": "Meeting or Job not found"}


def _rebuild_segments_only(db, meeting, aligned):
    """Replace derived Segments while retaining the Meeting's existing Speakers."""
    old_segments = (
        db.query(Segment).filter(Segment.meeting_id == meeting.id)
        .order_by(Segment.order).all()
    )
    edited = [
        {"start": row.start_time, "end": row.end_time, "text": row.text}
        for row in old_segments if row.is_edited
    ]
    speakers = {
        speaker.label: speaker
        for speaker in db.query(Speaker).filter(Speaker.meeting_id == meeting.id).all()
    }
    speaker_segments = {label: [] for label in speakers}
    db.query(Segment).filter(Segment.meeting_id == meeting.id).delete()
    db.flush()
    for index, derived in enumerate(aligned):
        text = derived["text"]
        is_edited = False
        for old in edited:
            if abs(derived["start"] - old["start"]) < 1.5 and abs(derived["end"] - old["end"]) < 1.5:
                text = old["text"]
                is_edited = True
                break
        db.add(Segment(
            meeting_id=meeting.id,
            speaker_id=speakers.get(derived["speaker"]).id if derived["speaker"] in speakers else None,
            start_time=derived["start"],
            end_time=derived["end"],
            text=text,
            original_text=derived["text"],
            order=index,
            is_edited=is_edited,
            confidence=derived.get("confidence"),
            corrections=[] if is_edited else derived.get("corrections", []),
        ))
        if derived["speaker"] in speaker_segments:
            speaker_segments[derived["speaker"]].append(derived)
    for label, speaker in speakers.items():
        assigned = speaker_segments[label]
        speaker.segment_count = len(assigned)
        speaker.total_speaking_time = sum(item["end"] - item["start"] for item in assigned)
    db.commit()


@celery_app.task(bind=True)
def reapply_vocabulary_task(self, meeting_id: str, job_id: str):
    """Re-derive Segments from stored Words and Turns without changing Speakers."""
    try:
        with meeting_job(meeting_id, job_id) as (db, meeting, job):
            words = words_from_stored(meeting.raw_transcription)
            if not words:
                raise RuntimeError("No existing transcription found. Run full processing first.")
            diarization = MeetingDiarization.from_stored(meeting.raw_diarization)
            if diarization is None:
                raise RuntimeError("No existing diarization found. Run full processing first.")
            correction = vocabulary_correction_for_meeting(db, meeting)
            aligned = derive_segments(
                words, diarization,
                switch_penalty=get_speaker_switch_penalty(),
                correction=correction,
            )
            update_progress(db, job, meeting, 80, "Saving corrected Segments...")
            _rebuild_segments_only(db, meeting, aligned)
        return {"status": "completed", "meeting_id": meeting_id}
    except MeetingNotFoundError:
        return {"error": "Meeting or Job not found"}
