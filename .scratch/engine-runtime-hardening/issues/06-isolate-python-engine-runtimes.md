# 06 - Isolate Python Engines in Dedicated Runtimes

**Plan:** `plans/006-isolate-python-engine-runtimes.md`

**What to build:** Move Qwen3-ASR and VibeVoice execution behind a strict,
versioned, file-based JSON subprocess protocol. Give each Engine an independently
pinned Python environment while preserving the existing Transcriber, Word, native
Turn, fallback, health, and Job failure contracts.

**Blocked by:** 01 - Degrade Safely When Optional Engine Capabilities Fail; 02 - Make Celery Task Failures Truthful; 03 - Pin Reproducible Engine Runtime Dependencies; 04 - Probe Engine Health Before Queueing Jobs; 05 - Add a Tiered Preset Smoke-Test Matrix.

**Status:** done

- [x] Core API/Celery code imports no Qwen or VibeVoice runtime package.
- [x] Qwen and VibeVoice run through independently pinned Python executables.
- [x] The versioned protocol strictly validates request, response, errors, Words, and native Turns.
- [x] Launching avoids shell strings and handles Windows paths, Unicode, timeout, cancellation, crashes, and cleanup.
- [x] Optional failures cross the process boundary as degradation; primary failures fail Jobs truthfully.
- [x] Fast health probes target the selected runtime and completed results record its fingerprint.
- [x] Fresh installers reconstruct both runtime environments and pass doctor plus smoke checks.
- [x] An ADR documents the isolation boundary and local-only guarantee.

**Verification:** Protocol/launcher tests pass (18 tests), runtime health/metadata
tests pass (37 tests), both isolated runtime CLIs import successfully, and doctor
reports Qwen3-ASR and VibeVoice ready when pointed at their immutable environments.
Installer syntax checks pass and the normal backend suite passes (227 tests, 20
explicit model-load/inference smokes deselected). Heavy smokes remain opt-in and
were not run to avoid exhausting local SSD, memory, and VRAM.
