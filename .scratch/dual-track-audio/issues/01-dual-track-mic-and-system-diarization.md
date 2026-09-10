# 01 - Dual-Track Audio Ingestion and Diarization (Mic + System / OBS)

**What to build:**
Enable dual-track audio ingestion and processing for meeting recordings, specifically targeting setups like OBS Studio where local microphone audio and remote meeting / desktop audio are captured on separate channels or files:
1. **API & Model Storage**:
   - Extend `models/meeting.py` to store optional paths for secondary audio tracks (`mic_audio_filepath`, `system_audio_filepath`) and dual-track metadata.
   - Update `POST /api/meetings` in `api/meetings.py` to accept two separate audio files (`file` as microphone and `system_file` as meeting/desktop audio) or automatically detect 2-channel (stereo L/R) and multi-stream audio containers from OBS via `ffprobe`.
2. **Audio Processing (`services/audio_service.py`)**:
   - Implement `extract_dual_audio`:
     - Process `mic.wav` (16kHz mono, loudnorm).
     - Process `system.wav` (16kHz mono, loudnorm).
     - Produce a mixed, balanced `audio.wav` (16kHz mono) for the frontend web player and unified ASR transcription.
   - Support splitting a stereo file (channel 0 = Mic, channel 1 = System) into the two mono files via `ffmpeg -map_channel` / `pan=mono|c0=...`.
3. **Deterministic + Neural Diarization Pipeline (`tasks/process_meeting.py`)**:
   - **Host / Local Mic Diarization**: Run `VadService` directly on `mic.wav` to extract active speech boundaries. Attribute all speech on this track deterministically to the local participant ("You" / Host) with 100% confidence, completely bypassing neural clustering for the local speaker.
   - **Remote Speakers Diarization**: Run the configured Diarizer (PyAnnote or VibeVoice) exclusively on `system.wav`. This isolates remote participants from the local microphone signal, eliminating acoustic mismatch and preventing cross-speaker confusion.
   - **Turn Merging & Overlap Handling**: Combine the host turns with remote speaker turns into a unified `DiarizationResult`. When the host and a remote participant talk simultaneously (crosstalk), both turns are preserved without interference.
   - Pass the merged turns and mixed transcript words into `build_segments` for millisecond-accurate word attribution.
4. **Frontend Upload Interface (`frontend/src/pages/HomePage.tsx`)**:
   - Add a tab or toggle in the "New transcription" modal: "Dual-track / OBS (Mic + Meeting Audio)".
   - Allow uploading two files (Microphone track + System audio track) or dragging a 2-channel / multi-track file.
   - Clearly label the host speaker as "You" by default in the speaker list.

**Blocked by:** 
- `.scratch/tasks-layer-refactor/issues/01-deduplicate-celery-tasks-and-lifecycle.md` (recommended to land first so the pipeline modifications integrate cleanly into the refactored `meeting_job` and `shared.py` structure).

**Status:** ready-for-agent

- [ ] Extend `models/meeting.py` with `mic_audio_filepath` and `system_audio_filepath`.
- [ ] Add dual-track extraction and channel splitting methods in `services/audio_service.py`.
- [ ] Update `POST /api/meetings` in `api/meetings.py` to handle dual-file uploads and probe multi-stream files.
- [ ] Implement dual-track diarization flow in `tasks/process_meeting.py`: VAD for mic track + Diarizer for system track.
- [ ] Add regression tests in `tests/test_audio_service.py` and `tests/test_dual_track.py` covering turn combination, crosstalk, and single-file fallback.
- [ ] Update frontend upload modal in `HomePage.tsx` to support selecting mic and system audio tracks.
