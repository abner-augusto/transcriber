import logging

log = logging.getLogger(__name__)

from .celery_app import celery_app
from .shared import (
    MeetingNotFoundError,
    meeting_job,
    update_progress,
    build_segments,
    prepare_diarization,
    rebuild_speakers_and_segments,
)
from engines import DIARIZER_ENGINE, make_aligner, make_diarizer, make_transcriber
from presets import resolve_preset
from services.audio_service import AudioService, DUAL_MIC_OUTPUT, DUAL_SYSTEM_OUTPUT
from services.speaker_id_service import SpeakerIdService
from services.vad_service import VadService
from tasks.dual_track import HOST_SPEAKER, build_dual_diarization, host_turns_from_vad


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
            words = transcriber.transcribe(audio_path, vocabulary=meeting.vocabulary)

            # Optional Step 2.5: Higher-precision CTC Forced Alignment
            if fa_enabled:
                update_progress(db, job, meeting, 46, "Refining word timestamps (CTC alignment)...")
                from engines import align_words
                words = align_words(audio_path, words, config=fa_config)

            raw_transcription_data = {
                "engine": preset["engine"],
                "preset": preset["id"],
                "words": [w.to_dict() for w in words],
            }
            runtime_fingerprint = getattr(transcriber, "runtime_fingerprint", None)
            if runtime_fingerprint:
                raw_transcription_data["runtime"] = {
                    "fingerprint": runtime_fingerprint,
                    "diagnostics": getattr(transcriber, "runtime_diagnostics", {}),
                }
            if hasattr(transcriber, "resolve_dtw_preset"):
                resolved_dtw = transcriber.resolve_dtw_preset()
                raw_transcription_data["dtw"] = resolved_dtw if (getattr(transcriber, "dtw_enabled", False) and resolved_dtw) else False

            meeting.raw_transcription = raw_transcription_data
            db.commit()
            update_progress(db, job, meeting, 48 if fa_enabled else 45, "Transcription complete")

            # Inter-stage cleanup: free transcriber and aligner VRAM before loading diarizer
            if hasattr(transcriber, "unload"):
                transcriber.unload()
            if fa_enabled:
                from engines.alignment import MMSCTCAligner
                MMSCTCAligner.unload()
            from engines.gpu_memory import release_gpu_memory
            release_gpu_memory()

            # Step 3: Diarization & VAD bounding
            vad_service = VadService()
            if meeting.is_dual_track:
                update_progress(db, job, meeting, 50, "Identifying speakers (dual-track)...")
                from config import get_meeting_path

                meeting_dir = get_meeting_path(meeting.id)
                mic_path = str(meeting_dir / DUAL_MIC_OUTPUT)
                system_path = str(meeting_dir / DUAL_SYSTEM_OUTPUT)

                # Host: deterministic VAD on the mic track — every speech region is the host.
                host_vad = vad_service.compute_vad_segments(mic_path)
                host_turns = host_turns_from_vad(host_vad)

                # Remote: Diarizer on the system track, bounded by VAD on that track.
                diar_result = diarizer.diarize(
                    system_path,
                    min_speakers=meeting.min_speakers,
                    max_speakers=meeting.max_speakers,
                )
                remote_turns = diar_result.turns
                system_vad = vad_service.compute_vad_segments(system_path)
                remote_turns = vad_service.mask_turns_to_vad(remote_turns, system_vad)

                diar_result = build_dual_diarization(host_turns, remote_turns)
                diar_engine_name = DIARIZER_ENGINE
                bounded_turns = diar_result.turns
                bounded_exclusive_turns = diar_result.exclusive_turns
                meeting.raw_diarization = {
                    "engine": diar_engine_name,
                    "turns": [t.to_dict() for t in bounded_turns],
                    "exclusive_turns": (
                        [t.to_dict() for t in bounded_exclusive_turns]
                        if bounded_exclusive_turns is not None
                        else None
                    ),
                    "overlaps": diar_result.overlaps,
                    "host_label": HOST_SPEAKER,
                }
            else:
                if getattr(transcriber, "has_native_diarization", False):
                    update_progress(db, job, meeting, 50, "Extracting native speaker diarization...")
                    diar_result = transcriber.get_native_diarization()
                    diar_engine_name = preset.get("engine", "vibevoice")
                else:
                    update_progress(db, job, meeting, 50, "Identifying speakers (diarization)...")
                    diar_result = diarizer.diarize(
                        audio_path,
                        min_speakers=meeting.min_speakers,
                        max_speakers=meeting.max_speakers,
                    )
                    diar_engine_name = DIARIZER_ENGINE

                diarization_data, bounded_turns, bounded_exclusive_turns = prepare_diarization(
                    diar_result, audio_path, vad_service
                )
                meeting.raw_diarization = {
                    "engine": diar_engine_name,
                    **diarization_data,
                }
            db.commit()
            update_progress(db, job, meeting, 70, "Diarization complete")

            # Free diarizer VRAM immediately after turns are extracted and saved
            if hasattr(diarizer, "unload"):
                diarizer.unload()
            from engines.gpu_memory import release_gpu_memory
            release_gpu_memory()

            # Step 4: Build the Segments a reader sees, from the Words and the Turns
            update_progress(db, job, meeting, 75, "Synchronizing speakers with text...")
            attribution_turns = (
                bounded_exclusive_turns
                if (bounded_exclusive_turns is not None and len(bounded_exclusive_turns) > 0)
                else bounded_turns
            )
            aligned = build_segments(words, attribution_turns, switch_penalty=switch_penalty)
            update_progress(db, job, meeting, 80, "Synchronization complete")

            # Step 5: Speaker naming (Participant N, overridden by voice profile matches)
            update_progress(db, job, meeting, 85, "Matching against saved voice profiles...")
            all_turns = bounded_turns + (bounded_exclusive_turns or [])
            speaker_labels = sorted({t.speaker for t in all_turns})
            host_label = HOST_SPEAKER if meeting.is_dual_track else None
            speaker_info = speaker_id_service.name_speakers(
                db, speaker_labels, bounded_turns, audio_path, host_label=host_label
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
