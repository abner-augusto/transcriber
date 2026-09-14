# 01 - Degrade Safely When Optional Engine Capabilities Fail

**Plan:** `plans/001-degrade-optional-engine-capabilities.md`

**What to build:** Make Qwen/VibeVoice forced-aligner initialization transactional
and optional. If processor or model loading fails, retain a diagnostic reason and
continue through the existing proportional timestamp fallback. Primary Transcriber
failures must still fail the Job.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] VibeVoice continues transcription when its optional forced aligner cannot load.
- [ ] Qwen3-ASR continues transcription when its optional forced aligner cannot load.
- [ ] Failed initialization leaves no partially initialized processor/model pair.
- [ ] A deterministic failure is logged once per Transcriber instance and is available for health diagnostics.
- [ ] Primary model failures still propagate.
- [ ] Regression tests cover unknown architecture, generic load failure, warning behavior, and proportional fallback output.

