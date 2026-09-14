# 06 - Isolate Python Engines in Dedicated Runtimes

**Plan:** `plans/006-isolate-python-engine-runtimes.md`

**What to build:** Move Qwen3-ASR and VibeVoice execution behind a strict,
versioned, file-based JSON subprocess protocol. Give each Engine an independently
pinned Python environment while preserving the existing Transcriber, Word, native
Turn, fallback, health, and Job failure contracts.

**Blocked by:** 01 - Degrade Safely When Optional Engine Capabilities Fail; 02 - Make Celery Task Failures Truthful; 03 - Pin Reproducible Engine Runtime Dependencies; 04 - Probe Engine Health Before Queueing Jobs; 05 - Add a Tiered Preset Smoke-Test Matrix.

**Status:** blocked

- [ ] Core API/Celery code imports no Qwen or VibeVoice runtime package.
- [ ] Qwen and VibeVoice run through independently pinned Python executables.
- [ ] The versioned protocol strictly validates request, response, errors, Words, and native Turns.
- [ ] Launching avoids shell strings and handles Windows paths, Unicode, timeout, cancellation, crashes, and cleanup.
- [ ] Optional failures cross the process boundary as degradation; primary failures fail Jobs truthfully.
- [ ] Fast health probes target the selected runtime and completed results record its fingerprint.
- [ ] Fresh installers reconstruct both runtime environments and pass doctor plus smoke checks.
- [ ] An ADR documents the isolation boundary and local-only guarantee.

