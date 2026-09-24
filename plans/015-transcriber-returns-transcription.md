# Plan 015: The Transcriber returns a Transcription

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` and the status of
> `.scratch/architecture-review/issues/01-transcriber-returns-transcription.md`.
>
> **Drift check (run first)**: `git diff --stat 72c88d0..HEAD -- engines/ engine_runners/ engine_runtimes/ tasks/ scripts/engine_smoke.py bench/compare_engines.py tests/fakes.py tests/task_harness.py`
> On a mismatch with "Current state", treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED (touches every adapter)
- **Depends on**: plan 012 (done). Independent of plan 014, but if 014 is in
  progress, land one of them first; both touch `tasks/process_meeting.py`.
- **Category**: architecture (deepening the Transcriber seam)
- **Planned at**: commit `72c88d0`, 2026-09-24
- **Source**: design session 2026-09-24 on ticket 01

## Why this matters

The Transcriber port has one method, but callers read seven optional
attributes through `hasattr`/`getattr`: `runtime_fingerprint`,
`runtime_diagnostics`, `resolve_dtw_preset`, `dtw_enabled`,
`has_native_diarization`, `get_native_diarization`, `unload`. Native
diarization is state that only exists after `transcribe()` returns.
`engine_runners/_main.py` and `scripts/engine_smoke.py` repeat the probing, and
the smoke test calls each Engine's private loaders. The pipeline knows which
Engine ran, which `CONTEXT.md` says it must not.

## Decisions (from the design session — do not re-litigate)

1. `transcribe()` returns an immutable `Transcription(words, native, provenance)`.
2. `provenance` is a dict the pipeline merges into `raw_transcription`
   without reading it. Each adapter owns its keys (`runtime`, `dtw`). The
   reserved keys `engine`, `preset`, `words` are never set by an adapter.
3. `unload()` is part of the port, required, a no-op where nothing is
   resident. Plan/ticket 04 may delete it later.
4. `load()` is part of the port: load weights where the Engine has them;
   for native executables (whisper.cpp, parakeet.cpp) check the executable
   and model file exist and raise otherwise.
5. Forced alignment stays a separate `Aligner` port (Words → Words); the
   pipeline replaces `transcription.words` with the aligned Words.
6. `Transcription` holds what the Engine produced or decided (e.g. the
   resolved DTW preset). What the user asked for (Preset, preferences) is
   ticket 03, recorded by the Job.
7. ADR-0006 protocol v1 does not change. The core `IsolatedPythonTranscriber`
   builds a `Transcription` from `EngineResponse`.
8. Stored `raw_transcription` keys stay exactly as today.

## Current state

- `engines/ports.py` — `Transcriber.transcribe(...) -> list[Word]`.
- `tasks/process_meeting.py:67-101` — transcribe, optional alignment, build
  `raw_transcription` with `runtime` (from `runtime_fingerprint` /
  `runtime_diagnostics`) and `dtw` (from `resolve_dtw_preset` /
  `dtw_enabled`), then `hasattr(transcriber, "unload")`; Step 3 reads
  `has_native_diarization` / `get_native_diarization`.
- Adapters: `faster_whisper.py` (classmethod `get_model`, classmethod
  `unload(model_path=None)`), `whisper_cpp.py` (`resolve_dtw_preset`,
  instance `unload`), `parakeet_cpp.py` (no load/unload),
  `isolated_python.py` (`load`, no-op `unload`, `get_native_diarization`),
  and the in-runtime adapters `qwen3_asr.py` / `vibevoice.py`
  (`_ensure_*_loaded`, `_aligner_unavailable_reason`, VibeVoice
  `get_native_diarization`).
- `engine_runners/_main.py:22-33` — `load` operation calls private loaders;
  transcribe path probes `has_native_diarization` and
  `_aligner_unavailable_reason`.
- `scripts/engine_smoke.py:36-48, 92-106` — private loaders and probing.
- Fakes: `tests/fakes.py::FakeTranscriber`,
  `tests/task_harness.py::NativeTranscriber`,
  `tests/test_task_failure_lifecycle.py::FailingTranscriber`.

## Target interface

```python
# engines/ports.py
@dataclass(frozen=True)
class Transcription:
    words: list[Word]
    native: DiarizationResult | None = None
    provenance: dict = field(default_factory=dict)   # JSON-serializable; merged into raw_transcription

@runtime_checkable
class Transcriber(Protocol):
    def load(self) -> None: ...
    def transcribe(self, audio_path: str, vocabulary: str | None = None) -> Transcription: ...
    def unload(self) -> None: ...
```

`RESERVED_PROVENANCE_KEYS = {"engine", "preset", "words"}`; a helper
`raw_transcription(engine, preset_id, transcription)` in `engines/ports.py`
builds the stored dict and raises if an adapter used a reserved key.

## Steps

### Step 1: Pin today's stored shape

Using `tests/task_harness.py`, add characterization tests that snapshot
`raw_transcription` for: a plain fake (keys `engine, preset, words`), a fake
with runtime fingerprint/diagnostics attributes (adds `runtime`), and a fake
with `resolve_dtw_preset`/`dtw_enabled` (adds `dtw`). They must pass on the
current code before any change.

### Step 2: Port, helper, fakes

Add `Transcription`, the new Protocol methods, and the helper. Update the
three fakes to return `Transcription` and implement `load`/`unload`
(`NativeTranscriber` returns `native=` in the value). Update the Step 1 fakes
to express the same data via `provenance`.

### Step 3: Adapters

- faster-whisper: instance `load()` → `get_model(...)`; instance `unload()`
  → the existing classmethod for this model path (keep the classmethod
  callable from `gpu_memory.unload_all_engines`).
- whisper.cpp: `provenance={"dtw": <resolved or False>}` exactly as the task
  computes it today; `load()` checks CLI and model paths.
- parakeet.cpp: `load()` checks CLI and model paths; `unload()` no-op.
- isolated runtime: `provenance={"runtime": {"fingerprint", "diagnostics"}}`,
  `native` from `response.native_turns`; drop `has_native_diarization`,
  `get_native_diarization`, and the instance attributes.
- in-runtime qwen3/vibevoice: public `load()` (their `_ensure_*` calls),
  `transcribe()` returns `Transcription` with `native` (VibeVoice) and
  `provenance={"alignment_degraded": ..., "alignment_reason": ...}`.
- `engine_runners/_main.py`: `load` op calls `adapter.load()`; transcribe op
  maps `Transcription` to `EngineResponse` (diagnostics = provenance).

### Step 4: Callers

- `tasks/process_meeting.py`: `transcription = transcriber.transcribe(...)`;
  alignment replaces `words`; `meeting.raw_transcription =
  raw_transcription(preset["engine"], preset["id"], transcription)`;
  `transcriber.unload()` unconditionally; Step 3 passes
  `native=transcription.native`, `native_engine=preset["engine"]` when not
  None. No `hasattr`/`getattr` on the transcriber remains.
- `scripts/engine_smoke.py`: `transcriber.load()`; `transcription.words` /
  `transcription.native`.
- `bench/compare_engines.py`: `.words`.

**Verify**: Step 1 snapshots pass unchanged; ordinary backend suite passes;
`rg "hasattr\(transcriber|getattr\(transcriber|getattr\(adapter" tasks scripts engine_runners`
returns nothing.

## Done criteria

- [ ] Stored `raw_transcription` snapshots unchanged
- [ ] No probing of a Transcriber anywhere outside tests
- [ ] Every adapter and fake implements `load`, `transcribe → Transcription`, `unload`
- [ ] Protocol v1 tests (`tests/test_engine_runtime_protocol.py`) unchanged and passing
- [ ] Smoke tiers run on the user's machine for parakeet.cpp and faster-whisper large-v3 (ADR-0007): `model_load` and `model_inference`
- [ ] `plans/README.md` row and ticket 01 status updated

## STOP conditions

- A snapshot needs its expected dict edited to pass.
- Any change to `engine_runtimes/protocol.py` seems necessary.
- The in-runtime adapters cannot return `Transcription` without importing
  core-only modules into the isolated venvs (check what `engines/ports.py`
  imports first; it must stay dependency-free).
