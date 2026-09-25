from .diarization import diarize_meeting
from jobs import MeetingNotFoundError, RunningJob, running
from meeting_store import rebuild_speakers_and_segments, replace_segments
from engines import make_diarizer
from preferences import hf_token
from services.speaker_id_service import SpeakerIdService
from services.vad_service import VadService
from transcript.diarization import MeetingDiarization
from transcript.segments import derive_segments
from transcript.words import words_from_stored
from .vocabulary import vocabulary_correction_for_meeting


def _reprocess_meeting(current: RunningJob, rerun_diarization: bool):
    """Shared execution logic for re-diarization and re-identification.

    When rerun_diarization is True, runs the Diarization stage again for fresh Turns —
    always through the Diarizer, never a Transcriber's native Turns.
    When False, reuses the Meeting's existing Turns and only re-names Speakers.
    """
    db, meeting, run_config = current.db, current.meeting, current.run_config
    words = words_from_stored(meeting.raw_transcription)
    if not words:
        raise RuntimeError("No existing transcription found. Run full processing first.")

    audio_path = meeting.audio_filepath
    if not audio_path:
        raise RuntimeError("No audio file found.")

    speaker_id_service = SpeakerIdService()

    if rerun_diarization:
        diarizer = make_diarizer(run_config, hf_token=hf_token())
        current.progress(10, "Running new speaker identification...")
        diarization = diarize_meeting(meeting, audio_path, diarizer=diarizer, vad_service=VadService())
        meeting.raw_diarization = diarization.to_stored()
        db.commit()
        current.progress(50, "Diarization complete")
    else:
        diarization = MeetingDiarization.from_stored(meeting.raw_diarization)
        if diarization is None or not diarization.turns:
            raise RuntimeError("No existing diarization found. Run full processing first.")

    current.progress(
        55 if rerun_diarization else 20,
        "Synchronizing speakers with text...",
    )
    correction = vocabulary_correction_for_meeting(
        db, meeting, enabled=run_config.vocabulary_correction.enabled
    )
    aligned = derive_segments(
        words, diarization, switch_penalty=run_config.speaker_switch_penalty, correction=correction
    )

    # Speaker naming (Participant N, overridden by voice profile matches)
    current.progress(
        65 if rerun_diarization else 40,
        "Matching against saved voice profiles...",
    )
    speaker_info = speaker_id_service.name_speakers(
        db,
        diarization.speaker_labels,
        diarization.turns,
        audio_path,
        host_label=diarization.host_label,
        speaker_profiles_enabled=run_config.speaker_profiles_enabled,
    )
    # Rebuild speakers and segments (preserving edits)
    current.progress(
        85 if rerun_diarization else 80,
        "Saving results...",
    )
    rebuild_speakers_and_segments(db, meeting, aligned, speaker_info, speaker_id_service)


def rediarize_task(meeting_id: str, job_id: str):
    """Re-run diarization without re-transcribing.

    Keeps the Meeting's existing Words, runs the Diarizer again for fresh Turns, and
    rebuilds the Segments from both. Preserves manually edited segment text.
    """
    try:
        with running(meeting_id, job_id) as current:
            _reprocess_meeting(current, rerun_diarization=True)
        return {"status": "completed", "meeting_id": meeting_id}
    except MeetingNotFoundError:
        return {"error": "Meeting or Job not found"}


def reidentify_task(meeting_id: str, job_id: str):
    """Re-run speaker naming without re-transcribing or re-diarizing.

    Reuses the Meeting's existing Words and Turns and only re-names the Speakers against
    the saved Voice Profiles. This is how a newly-saved Voice Profile gets applied to an
    already-processed Meeting. Preserves edited text.
    """
    try:
        with running(meeting_id, job_id) as current:
            _reprocess_meeting(current, rerun_diarization=False)
        return {"status": "completed", "meeting_id": meeting_id}
    except MeetingNotFoundError:
        return {"error": "Meeting or Job not found"}


def reapply_vocabulary_task(meeting_id: str, job_id: str):
    """Re-derive Segments from stored Words and Turns without changing Speakers."""
    try:
        with running(meeting_id, job_id) as current:
            db, meeting, run_config = current.db, current.meeting, current.run_config
            words = words_from_stored(meeting.raw_transcription)
            if not words:
                raise RuntimeError("No existing transcription found. Run full processing first.")
            diarization = MeetingDiarization.from_stored(meeting.raw_diarization)
            if diarization is None:
                raise RuntimeError("No existing diarization found. Run full processing first.")
            correction = vocabulary_correction_for_meeting(
                db, meeting, enabled=run_config.vocabulary_correction.enabled
            )
            aligned = derive_segments(
                words, diarization,
                switch_penalty=run_config.speaker_switch_penalty,
                correction=correction,
            )
            current.progress(80, "Saving corrected Segments...")
            replace_segments(db, meeting, aligned)
        return {"status": "completed", "meeting_id": meeting_id}
    except MeetingNotFoundError:
        return {"error": "Meeting or Job not found"}
