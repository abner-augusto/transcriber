# 03 - Enable DTW Timestamps in whisper.cpp

**What to build:** Give whisper.cpp Words tighter timing around speaker changes by enabling and invoking a model-appropriate DTW preset when the installed CLI supports it, while keeping transcription usable on builds without DTW.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] The supported whisper.cpp build configuration enables DTW.
- [ ] The Transcriber passes a configured DTW preset appropriate for the selected model.
- [ ] The active DTW setting is visible in diagnostic logs or job diagnostics.
- [ ] Unsupported or unavailable DTW capability produces a clear warning and a controlled fallback to the existing timestamp path.
- [ ] Configuration and installation guidance explains how to verify the CLI flag and select the preset.
- [ ] Tests cover command construction, default behavior, and capability/fallback handling.
