from .celery_app import celery_app
from .shared import (
    MeetingNotFoundError,
    meeting_job,
    update_progress,
    build_segments,
    prepare_diarization,
    rebuild_speakers_and_segments,
    words_from_stored,
    turns_from_stored,
    exclusive_turns_from_stored,
)
from engines import DIARIZER_ENGINE, make_diarizer
from preferences import get_speaker_switch_penalty
from services.speaker_id_service import SpeakerIdService
from services.vad_service import VadService


def _reprocess_meeting(db, meeting, job, rerun_diarization: bool):
    """Shared execution logic for re-diarization and re-identification.

    When rerun_diarization is True, runs the Diarizer again for fresh Turns.
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
        if hasattr(diarizer, "unload"):
            diarizer.unload()
        from engines.gpu_memory import release_gpu_memory
        release_gpu_memory()
    else:
        bounded_turns = turns_from_stored(meeting.raw_diarization)
        bounded_exclusive_turns = exclusive_turns_from_stored(meeting.raw_diarization)
        if not bounded_turns:
            raise RuntimeError("No existing diarization found. Run full processing first.")

    # Build segments from Words and Turns
    attribution_turns = (
        bounded_exclusive_turns
        if (bounded_exclusive_turns is not None and len(bounded_exclusive_turns) > 0)
        else bounded_turns
    )
    update_progress(
        db, job, meeting,
        55 if rerun_diarization else 20,
        "Synchronizing speakers with text...",
    )
    aligned = build_segments(
        words,
        attribution_turns,
        switch_penalty=get_speaker_switch_penalty(),
    )

    # Speaker naming (Participant N, overridden by voice profile matches)
    update_progress(
        db, job, meeting,
        65 if rerun_diarization else 40,
        "Matching against saved voice profiles...",
    )
    all_turns = bounded_turns + (bounded_exclusive_turns or [])
    speaker_labels = sorted({t.speaker for t in all_turns})
    speaker_info = speaker_id_service.name_speakers(
        db, speaker_labels, bounded_turns, audio_path
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
