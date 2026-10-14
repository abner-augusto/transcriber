from .diarization import diarize_meeting
from jobs import MeetingNotFoundError, RunningJob, running
from meeting_store import labels_with_segments, rebuild_speakers_and_segments, replace_segments
from engines import make_diarizer
from preferences import hf_token
from services.audio_retention import drop_processed_tracks, processed_tracks_present
from services.audio_service import AudioService
from services.source_reference import locate_tracks
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

    made_tracks = False
    if rerun_diarization:
        diarizer = make_diarizer(run_config, hf_token=hf_token())
        if meeting.is_dual_track and not processed_tracks_present(meeting.id):
            # The app dropped the processed tracks (plan 045): make them again from the
            # original recordings, and drop them again when this Job ends.
            current.progress(5, "Extracting the mic and system tracks from the originals...")
            tracks = locate_tracks(meeting)
            db.commit()
            made_tracks = True
            AudioService().extract_dual_tracks(str(tracks.mic), str(tracks.system), meeting.id)
        current.progress(10, "Running new speaker identification...")
        try:
            diarization = diarize_meeting(meeting, audio_path, diarizer=diarizer, vad_service=VadService())
        finally:
            if made_tracks:
                drop_processed_tracks(meeting.id)
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
        words, diarization, switch_penalty=run_config.speaker_switch_penalty, correction=correction,
        splits=meeting.split_times or [],
    )

    # Speaker naming (Participant N, overridden by voice profile matches)
    current.progress(
        65 if rerun_diarization else 40,
        "Matching against saved voice profiles...",
    )
    speaker_info = speaker_id_service.name_speakers(
        db,
        labels_with_segments(aligned),
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
    # Re-diarizing makes new Turns, so labels mean new people; otherwise they are stable.
    rebuild_speakers_and_segments(
        db, meeting, aligned, speaker_info, speaker_id_service,
        keep="overlap" if rerun_diarization else "labels",
    )


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
                splits=meeting.split_times or [],
            )
            current.progress(80, "Saving corrected Segments...")
            replace_segments(db, meeting, aligned)
        return {"status": "completed", "meeting_id": meeting_id}
    except MeetingNotFoundError:
        return {"error": "Meeting or Job not found"}
