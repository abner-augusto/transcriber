# 01 - Frontend Settings: Engine and Model Selector

**What to build:** Update the Settings screen in the frontend to allow configuring transcription engines and presets, explicitly supporting `qwen3-asr` and `vibevoice` (as its own engine with model `VibeVoice-ASR-Streaming-7B`).

**Blocked by:** None — can start immediately.

**Status:** completed

- [x] Fetch available engines and presets from `GET /api/model-settings`.
- [x] Display `vibevoice` as a dedicated engine selector with its available 7B model.
- [x] Display `qwen3-asr` with model `Qwen3-ASR 1.7B` and indicate posterior diarization mode.
- [x] Allow setting default preset and modifying preset parameters via API.
