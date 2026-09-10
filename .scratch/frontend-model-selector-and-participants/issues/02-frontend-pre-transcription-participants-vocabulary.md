# 02 - Frontend Pre-Transcription: Replace AI Speaker Toggle with Known Participants

**What to build:** In the pre-transcription upload / configuration screen, remove the AI speaker identification toggle. In its place, ask the user to input the names of all known meeting participants. Feed this list directly into the meeting vocabulary so it primes the model's system prompt / context hotwords.

**Blocked by:** 01-frontend-settings-model-and-engine-selector.md

**Status:** completed

- [x] Remove the AI speaker identification toggle from the pre-transcription screen.
- [x] Add an input component for entering names of all known speakers in the meeting (e.g. tag/chip list or comma-separated names).
- [x] Merge the entered participant names into the `vocabulary` field sent to `POST /api/meetings`.
- [x] Verify that `vocabulary` flows directly into the ASR models (`--context` in Qwen3-ASR and `context_info` in VibeVoice).
