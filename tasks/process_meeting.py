import logging

log = logging.getLogger(__name__)

from .celery_app import celery_app
from dataclasses import replace
from .diarization import diarize_meeting
from .shared import (
    MeetingNotFoundError,
    meeting_job,
    update_progress,
    rebuild_speakers_and_segments,
)
from engines import make_aligner, make_diarizer, make_transcriber, raw_transcription
from presets import resolve_preset
from services.audio_service import AudioService
from services.speaker_id_service import SpeakerIdService
from services.vad_service import VadService
from transcript.segments import derive_segments
from .vocabulary import vocabulary_correction_for_meeting


@celery_app.task(bind=True)
def process_meeting_task(self, meeting_id: str, job_id: str):
    """Main pipeline: audio extraction -> transcription -> diarization -> segments -> speaker naming."""
    try:
        with meeting_job(meeting_id, job_id) as (db, meeting, job):
            audio_service = AudioService()
            speaker_id_service = SpeakerIdService()

            preset = resolve_preset(meeting.preset_id)
            transcriber = make_transcriber(preset)
            diarizer = make_diarizer()

            from preferences import get_speaker_switch_penalty, load_preferences
            prefs = load_preferences()
            switch_penalty = get_speaker_switch_penalty()
            fa_pref = prefs.get("forced_alignment", {})
            fa_enabled = bool(
                preset.get("forced_alignment")
                or (isinstance(fa_pref, dict) and fa_pref.get("enabled"))
                or (isinstance(fa_pref, bool) and fa_pref)
            )
            fa_config = dict(fa_pref) if isinstance(fa_pref, dict) else {}
            if isinstance(preset.get("forced_alignment"), dict):
                fa_config.update(preset["forced_alignment"])
            # Validate the selected engine before any processing work begins.
            if fa_enabled:
                make_aligner(fa_config)

            # Step 1: Extract audio
            update_progress(db, job, meeting, 2, "Extracting audio...")
            if meeting.is_dual_track:
                audio_path = audio_service.extract_dual_audio(
                    meeting.mic_audio_filepath, meeting.system_audio_filepath, meeting.id
                )
            else:
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
            transcriber.load()
            try:
                transcription = transcriber.transcribe(audio_path, vocabulary=meeting.vocabulary)
                words = transcription.words

                # Optional Step 2.5: Higher-precision CTC Forced Alignment
                if fa_enabled:
                    update_progress(db, job, meeting, 46, "Refining word timestamps (CTC alignment)...")
                    from engines import align_words
                    words = align_words(audio_path, words, config=fa_config)
                    transcription = replace(transcription, words=words)

                meeting.raw_transcription = raw_transcription(
                    preset["engine"], preset["id"], transcription
                )
                db.commit()
                update_progress(db, job, meeting, 48 if fa_enabled else 45, "Transcription complete")
            finally:
                # Release Transcriber resources before loading the Diarizer.
                transcriber.unload()

            if fa_enabled:
                from engines.alignment import MMSCTCAligner
                MMSCTCAligner.unload()
            from engines.gpu_memory import release_gpu_memory
            release_gpu_memory()

            # Step 3: Diarization & VAD bounding
            def report_diarization_path(path: str) -> None:
                step = {
                    "dual_track": "Identifying speakers (dual-track)...",
                    "native": "Extracting native speaker diarization...",
                    "diarizer": "Identifying speakers (diarization)...",
                }[path]
                update_progress(db, job, meeting, 50, step)

            diarization = diarize_meeting(
                meeting,
                audio_path,
                diarizer=diarizer,
                vad_service=VadService(),
                native=transcription.native,
                native_engine=preset["engine"] if transcription.native is not None else None,
                on_path=report_diarization_path,
            )
            meeting.raw_diarization = diarization.to_stored()
            db.commit()
            update_progress(db, job, meeting, 70, "Diarization complete")

            # Free diarizer VRAM immediately after turns are extracted and saved
            if hasattr(diarizer, "unload"):
                diarizer.unload()
            from engines.gpu_memory import release_gpu_memory
            release_gpu_memory()

            # Step 4: Build the Segments a reader sees, from the Words and the Turns
            update_progress(db, job, meeting, 75, "Synchronizing speakers with text...")
            correction = vocabulary_correction_for_meeting(db, meeting)
            aligned = derive_segments(
                words, diarization, switch_penalty=switch_penalty, correction=correction
            )
            update_progress(db, job, meeting, 80, "Synchronization complete")

            # Step 5: Speaker naming (Participant N, overridden by voice profile matches)
            update_progress(db, job, meeting, 85, "Matching against saved voice profiles...")
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

            # Step 6: Save results (preserving edits)
            update_progress(db, job, meeting, 90, "Saving results...")
            rebuild_speakers_and_segments(db, meeting, aligned, speaker_info, speaker_id_service)

        return {"status": "completed", "meeting_id": meeting_id}

    except MeetingNotFoundError:
        return {"error": "Meeting or Job not found"}
