# 01 - Transcriber Returns a Transcription

**Source:** architecture review 2026-09-24, candidate 2.

**What to build:** Change the Transcriber port so `transcribe()` returns one
immutable `Transcription` value (Words, optional native Turns, provenance such
as runtime fingerprint, diagnostics, and resolved DTW preset) instead of a
bare Word list plus optional attributes the pipeline probes afterwards.

**Why:** `tasks/process_meeting.py` reads seven optional adapter attributes
through `hasattr`/`getattr` (`runtime_fingerprint`, `runtime_diagnostics`,
`resolve_dtw_preset`, `dtw_enabled`, `has_native_diarization`,
`get_native_diarization`, `unload`). Native diarization is state that exists
only after `transcribe()` runs. `engine_runners/_main.py` and
`scripts/engine_smoke.py` repeat the same probing. The pipeline therefore
knows which Engine ran, which `CONTEXT.md` says it must not.

**Blocked by:** None. Plan 012 is done: `tasks.diarization.diarize_meeting` takes
`native` / `native_engine`, which collapse into the `Transcription` value.

**Status:** in-progress

**Plan:** `plans/015-transcriber-returns-transcription.md` (design session 2026-09-24:
provenance dict, `load`/`unload` on the port, Aligner stays separate, RunConfig stays out).

**Constraints:**
- ADR-0006: the JSON protocol v1 between core and isolated runners does not
  change; only the core adapter builds a `Transcription` from `EngineResponse`.
- ADR-0007: validate against parakeet.cpp and faster-whisper large-v3 first.

**Open questions for the exploration session:**
- Is `unload` part of this seam or of the model-residency ticket (04)?
- Does `Transcription` carry the resolved Preset/RunConfig (ticket 03) or only
  what the Engine itself decided?
- Keep `Aligner` as a separate port, or make alignment a step that maps
  `Transcription → Transcription`?

**Acceptance criteria (draft):**
- [ ] No `hasattr`/`getattr` on a Transcriber anywhere in `tasks/`, `scripts/`, `engine_runners/`
- [ ] Every adapter and `tests/fakes.py::FakeTranscriber` returns `Transcription`
- [ ] `raw_transcription` stored JSON keeps its current keys

**Outcome:** Implementation and ordinary backend verification are complete.
User-only `model_load` and `model_inference` smoke tiers for parakeet.cpp and
faster-whisper large-v3 are pending. Run them locally and record results before
resolving this issue.
