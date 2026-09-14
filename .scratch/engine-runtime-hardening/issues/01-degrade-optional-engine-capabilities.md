# 01 - Degrade Safely When Optional Engine Capabilities Fail

**Plan:** `plans/001-degrade-optional-engine-capabilities.md`

**What to build:** Make Qwen/VibeVoice forced-aligner initialization transactional
and optional. If processor or model loading fails, retain a diagnostic reason and
continue through the existing proportional timestamp fallback. Primary Transcriber
failures must still fail the Job.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] VibeVoice continues transcription when its optional forced aligner cannot load.
- [x] Qwen3-ASR continues transcription when its optional forced aligner cannot load.
- [x] Failed initialization leaves no partially initialized processor/model pair.
- [x] A deterministic failure is logged once per Transcriber instance and is available for health diagnostics.
- [x] Primary model failures still propagate.
- [x] Regression tests cover unknown architecture, generic load failure, warning behavior, and proportional fallback output.

**Verification:** `venv\Scripts\python.exe -m pytest tests/test_engines.py -q`
passes (37 tests); the resource-limited backend suite passes (183 tests).
