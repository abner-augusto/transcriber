import logging

log = logging.getLogger(__name__)

from dataclasses import replace
from .diarization import diarize_meeting
from jobs import MeetingNotFoundError, running
from meeting_store import labels_with_segments, rebuild_speakers_and_segments
from engines import make_aligner, make_diarizer, make_transcriber, raw_transcription
from config import get_meeting_path
from services.audio_retention import delete_raw_audio, forget_raw_audio
from services.source_reference import locate_tracks
from services.audio_service import AudioService
from services.speaker_id_service import SpeakerIdService
from services.vad_service import VadService
from transcript.segments import derive_segments
from .vocabulary import vocabulary_correction_for_meeting


def process_meeting_task(meeting_id: str, job_id: str):
    """Main pipeline: audio extraction -> transcription -> diarization -> segments -> speaker naming."""
    try:
        with running(meeting_id, job_id) as current:
            db, meeting = current.db, current.meeting
            audio_service = AudioService()
            speaker_id_service = SpeakerIdService()

            run_config = current.run_config
            preset = run_config.preset
            transcriber = make_transcriber(run_config)
            from preferences import hf_token
            diarizer = make_diarizer(run_config, hf_token=hf_token())
            switch_penalty = run_config.speaker_switch_penalty
            fa_enabled = run_config.forced_alignment is not None
            # Validate the selected engine before any processing work begins.
            if fa_enabled:
                make_aligner(run_config)

            # A first transcription saves each stage as it finishes, so a late failure still
            # leaves Words and Turns to Re-diarize from. A Reprocessing of a COMPLETED Meeting
            # saves nothing until its one final transaction, so stopping it (plan 048) leaves
            # the previous transcript, audio and duration exactly as they were.
            reprocessing = current.reprocessing

            # Step 1: Extract audio
            current.progress(2, "Extracting audio...")
            deferred_mix = reprocessing and bool(meeting.is_dual_track)
            if meeting.is_dual_track:
                # The tracks the app holds, or the originals where their Source References
                # say they are. Either way they are only read.
                tracks = locate_tracks(meeting)
                db.commit()  # a path found by searching is remembered
                audio_path = audio_service.extract_dual_audio(
                    str(tracks.mic), str(tracks.system), meeting.id, layout=meeting.track_layout,
                    defer_mix=deferred_mix,
                )
            else:
                audio_path = audio_service.extract_audio(
                    meeting.audio_filepath, meeting.id,
                    track=(meeting.track_layout or {}).get("audio"),
                )
            # Where the audio lives once saved: a deferred mix is read from audio.part.wav
            # meanwhile and moved over audio.wav after the commit.
            saved_audio_path = (
                str(get_meeting_path(meeting.id) / "audio.wav") if deferred_mix else audio_path
            )
            duration = audio_service.get_duration(audio_path)
            if not reprocessing:
                meeting.duration = duration
                meeting.audio_filepath = saved_audio_path
                db.commit()
            current.progress(5, "Audio extracted")

            # Step 2: Transcription
            current.progress(10, f"Transcribing with {preset['name']}...")
            transcriber.load()
            transcription = transcriber.transcribe(audio_path, vocabulary=meeting.vocabulary)
            words = transcription.words

            # Optional Step 2.5: Higher-precision CTC Forced Alignment
            if fa_enabled:
                current.progress(46, "Refining word timestamps (CTC alignment)...")
                from engines import align_words
                words = align_words(audio_path, words, run_config=run_config)
                transcription = replace(transcription, words=words)

            stored_transcription = raw_transcription(preset["engine"], preset["id"], transcription)
            if not reprocessing:
                meeting.raw_transcription = stored_transcription
                db.commit()
            current.progress(48 if fa_enabled else 45, "Transcription complete")

            # Step 3: Diarization & VAD bounding
            def report_diarization_path(path: str) -> None:
                step = {
                    "dual_track": "Identifying speakers (dual-track)...",
                    "native": "Extracting native speaker diarization...",
                    "diarizer": "Identifying speakers (diarization)...",
                }[path]
                current.progress(50, step)

            diarization = diarize_meeting(
                meeting,
                audio_path,
                diarizer=diarizer,
                vad_service=VadService(),
                native=transcription.native,
                on_path=report_diarization_path,
            )
            stored_diarization = diarization.to_stored()
            if not reprocessing:
                meeting.raw_diarization = stored_diarization
                db.commit()
            current.progress(70, "Diarization complete")

            # Step 4: Build the Segments a reader sees, from the Words and the Turns
            current.progress(75, "Synchronizing speakers with text...")
            correction = vocabulary_correction_for_meeting(
                db, meeting, enabled=run_config.vocabulary_correction.enabled
            )
            aligned = derive_segments(
                words, diarization, switch_penalty=switch_penalty, correction=correction,
                splits=meeting.split_times or [],
            )
            current.progress(80, "Synchronization complete")

            # Step 5: Speaker naming (Participant N, overridden by voice profile matches)
            current.progress(85, "Matching against saved voice profiles...")
            speaker_info = speaker_id_service.name_speakers(
                db,
                labels_with_segments(aligned),
                diarization.turns,
                audio_path,
                host_label=diarization.host_label,
                speaker_profiles_enabled=run_config.speaker_profiles_enabled,
            )
            # Step 6: Save results (preserving edits)
            current.progress(90, "Saving results...")
            # Nothing below commits: `running` saves all of it with the Job's COMPLETED in
            # one transaction, so a cancel finds the Job either finished or untouched.
            meeting.duration = duration
            meeting.audio_filepath = saved_audio_path
            meeting.raw_transcription = stored_transcription
            meeting.raw_diarization = stored_diarization
            # A first run has no manual Speakers; a re-run of a processed Meeting has new Turns.
            rebuild_speakers_and_segments(
                db, meeting, aligned, speaker_info, speaker_id_service, keep="overlap"
            )

            # The originals live outside the app; keep only the derived audio (plan 045).
            forget_raw_audio(meeting)

            def after_commit():
                try:
                    if deferred_mix:
                        audio_service.install_mix(meeting_id)
                finally:
                    delete_raw_audio(meeting_id, saved_audio_path)

            current.after_commit(after_commit)

        return {"status": "completed", "meeting_id": meeting_id}

    except MeetingNotFoundError:
        return {"error": "Meeting or Job not found"}
