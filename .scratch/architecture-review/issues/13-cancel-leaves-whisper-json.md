# 13 - Cancel Leaves the whisper-cli JSON Behind

**Source:** manual QA of the Cancel button (plan 048), 2026-10-25.

**What happened:** after a Job is cancelled and the Meeting goes back to UPLOADED
or FAILED, the cleanup deletes `audio.wav` but leaves `audio.wav.json` in the
Meeting's storage folder. That file is whisper-cli's full-JSON output:
`engines/whisper_cpp.py` passes `-of <audio_path>`, so whisper-cli writes
`<audio_path>.json` next to the audio.

**Effect:** a small orphan file per cancelled Whisper run. A stale JSON could
also be read by a later run if whisper-cli fails without overwriting it. The
fallback path reads `output_json` after a zero exit code, so this is unlikely
but possible.

**What to build:** remove `audio.wav.json` wherever `audio.wav` is removed
(`services/audio_retention.py`). Better: have `WhisperCppEngine` delete its
output JSON once it has parsed it, so the file never outlives the call.

**Acceptance:**
- After a cancelled first transcription with Whisper, the Meeting folder holds
  only the uploads.
- A test covering the engine's JSON removal, or the retention cleanup's.

**Status:** ready-for-agent
