# Plan 022: Nemotron 3 Diarization as a second Diarizer Engine

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report; do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 748cf57..HEAD -- engines/ engine_runners/ engine_runtimes/ tasks/diarization.py tasks/dual_track.py tasks/reprocess_task.py tasks/process_meeting.py preferences.py run_config.py main.py config.py install.ps1 install.sh`
> On a mismatch with "Current state", treat it as a STOP condition.

## Status

- **Execution status**: TODO
- **Priority**: P2
- **Effort**: M
- **Risk**: MED (new isolated runtime, touches the Diarization stage)
- **Depends on**: none. Plan 023 (the settings UI) depends on this plan.
- **Category**: new Engine
- **Planned at**: commit `748cf57`, 2026-09-25
- **Source**: bench session 2026-09-25 (`bench/diarizer_wder.py`)

## Why this matters

On the user's own Meetings, with the Words held fixed (parakeet.cpp q8_0) and
only the Turns swapped, NVIDIA Nemotron 3 Diarization attributed fewer Words to
the wrong Speaker than pyannote community-1:

| Meeting | pyannote | Nemotron |
|---|---|---|
| Arquitetura 03 (single track, 4 speakers, 36 min) | 1.60% WDER | 0.73% |
| Sinop 2026-09-22 (dual track, 65 min) | 2.80% | 2.08% |

It ran at ~350x realtime in under 1 GB of VRAM. The model is ungated (OpenMDW
license), so it needs no Hugging Face token. Voice Profiles are unaffected:
their embeddings come from SpeechBrain in `services/embedding_service.py`, not
from pyannote.

## Decisions (do not re-litigate)

1. **The Diarizer is a Preference, not a Preset.** A Preset names a
   Transcriber. Add `engine` to `DiarizationPrefs`; the Job's `RunConfig`
   captures it the same way it captures the clustering knobs today.
2. **Engine ids**: `pyannote` (default, unchanged behavior) and
   `nemotron-3-diarization`. The default stays `pyannote` until the user flips
   it in the UI (plan 023). No automatic migration of `preferences.json`.
3. **Nemotron runs in its own isolated runtime** (ADR-0006), not in `.venv`.
   It needs Transformers with `nemotron3_diarization`, which no release has at
   planning time (5.17.0 lacks it). Pin
   `transformers @ git+https://github.com/huggingface/transformers@11c16613d93911300c38ec8c9c2460567be53281`
   through the manifest's `sources` (as VibeVoice pins its source). Replace
   the pin with the first release that ships the model.
4. **Protocol v1 gains a `diarize` operation.** It adds a value, not a field,
   so there is no schema bump. A `diarize` response has `words: []` and
   carries the Turns in `native_diarization`. `engine_id`
   `nemotron-3-diarization` joins the allowed set; `threshold` joins
   `_OPTION_FIELDS`.
5. **Weights are installed locally, never downloaded during a Job.** The
   installers snapshot `nvidia/Nemotron-3-Diarization` into
   `models/nemotron-diarization/`. The runner loads that path with
   `local_files_only=True` (ADR-0001).
6. **Offline mode, default threshold 0.5**, exactly what the bench measured
   (`bench/run_nemotron_diarization.py`). No streaming.
7. **Speakers with less than 5 s of speech in the whole Meeting are dropped.**
   The bench found a 3.6 s phantom third remote speaker that got no Words. It
   would surface as an empty "Participant N". Drop it in the core adapter;
   the constant lives there with this reason.
8. **Exclusive Turns are computed from overlaps**, as the bench did. Move
   `compute_exclusive_turns` from `tasks/dual_track.py` to `engines/overlap.py`
   (engines must not import tasks) and keep a re-export in `tasks/dual_track.py`.
9. **`min_speakers` is ignored and `max_speakers` is capped at 8** by the
   model itself. Log both at INFO when they were set. pyannote's clustering
   knobs do not apply to Nemotron; the adapter ignores them.
10. **No silent fallback.** If the selected Diarizer is blocked, queueing is
    refused with 409, the same way a blocked Preset is today. A runtime failure
    fails the Job (plan 002 semantics).
11. **The stored diarization names the Engine that ran.** Use the existing
    `DiarizationResult.engine`. The stage records `result.engine`, falling back
    to `pyannote` for results that do not set it.

## Current state

- `engines/__init__.py:41` — `DIARIZER_ENGINE = "pyannote"`;
  `make_diarizer(run_config, *, hf_token)` (line ~124) always returns
  `PyannoteDiarizer`.
- `tasks/diarization.py` — `bound_to_speech(..., engine=DIARIZER_ENGINE)` and
  `_diarize_dual_track` records `engine=DIARIZER_ENGINE`.
- `tasks/process_meeting.py:28-29` and `tasks/reprocess_task.py:33` call
  `make_diarizer(run_config, hf_token=hf_token())`.
- `tasks/dual_track.py` — `compute_exclusive_turns`.
- `preferences.py:47` — `DiarizationPrefs` (`clustering_threshold`, `Fa`,
  `Fb`, all numbers, `extra="forbid"`); the patch at ~line 261 accepts numbers
  only.
- `run_config.py` — `RunConfig.diarization: DiarizationPrefs`.
- `engine_runtimes/protocol.py` — `engine_id` in `{"qwen3-asr", "vibevoice"}`,
  `operation` in `{"load", "transcribe"}`.
- `engine_runners/_main.py` — `run(engine_id, factory)` handles `load` and
  `transcribe`.
- `engines/isolated_python.py` — `IsolatedPythonTranscriber` picks its Python
  by `engine_id` from `config.settings`.
- `engines/health.py` — `_manifest_probe` picks the runtime Python with the
  same two-way conditional; `probe_engine` routes manifest Engines by name.
- `api/meetings.py:30` — `_require_usable_preset` refuses blocked Presets with 409.
- `main.py:126` — `GET /api/settings` returns `{"preferences": ...}`.
- `install.ps1:66` / `install.sh` — runtime loop over `qwen3-asr vibevoice`.
- Bench reference implementation: `bench/run_nemotron_diarization.py`,
  scoring: `bench/diarizer_wder.py`.

## Steps

### Step 1: Pin today's behavior

Add tests that pass on the current code:

- `make_diarizer` with default `RunConfig` returns a `PyannoteDiarizer`.
- The single-track and dual-track stages store `engine == "pyannote"`
  (use the fakes in `tests/fakes.py` / `tests/task_harness.py`).
- `apply_preferences_request({"diarization": {"clustering_threshold": 0.6}})`
  stores the threshold, as today.

**Verify**: `.\.venv\Scripts\python.exe -m pytest -q tests` passes.

### Step 2: Preference and RunConfig

- `DiarizationPrefs.engine: Literal["pyannote", "nemotron-3-diarization"] = "pyannote"`.
- The patch in `apply_preferences_request` accepts `engine` when it is one of
  those strings and keeps the numeric keys as today. An unknown engine string
  is ignored, the way invalid numbers are ignored today.
- `public()` exposes it. Existing `preferences.json` files without the field
  load as `pyannote`.

**Verify**: new tests for the patch (valid, unknown, missing) and for a
`preferences.json` without `engine`. Suite passes.

### Step 3: Runtime manifest, requirements, installers

- `engine_runtimes/manifests/nemotron-diarization.json` modelled on
  `qwen3-asr.json`: `runtime_id` `nemotron-diarization-v1`; packages
  `transformers` (the pinned commit via `sources`), `torch >=2.11,<2.12`,
  `torchaudio ==2.11.0`, `librosa`, `soundfile`;
  `model_types: ["nemotron3_diarization"]`; required import
  `transformers.models.auto.modeling_auto:AutoModelForAudioFrameClassification`.
- `requirements/engines/nemotron-diarization.txt` with the same pins.
- `config.py`: `nemotron_diarization_python` and
  `nemotron_diarization_model_path = "./models/nemotron-diarization"`.
- `install.ps1` / `install.sh`: add `nemotron-diarization` to the runtime
  loop, and snapshot the model into `models/nemotron-diarization`
  (`huggingface_hub.snapshot_download`, `allow_patterns` limited to
  `config.json`, `model.safetensors`, `processor_config.json`).
- Replace the two-way `settings.qwen3_asr_python if ... else
  settings.vibevoice_python` in `engines/isolated_python.py` and
  `engines/health.py` with one lookup table in `config.py` or
  `engine_runtimes`, used by both.

**Verify**: `.\.venv\Scripts\python.exe -m engine_runtimes.manifest nemotron-diarization`
validates the manifest; the installer checks in `tests/` pass.

### Step 4: Protocol and runner

- Protocol: `diarize` operation, `nemotron-3-diarization` engine id,
  `threshold` option. Unit tests for accepted/rejected requests, and a
  response with `words: []` plus Turns that round-trips.
- `engine_runners/_main.py`: when `operation == "diarize"`, call
  `adapter.diarize(request.audio_path)` and write its Turns to
  `native_diarization`.
- `engine_runners/nemotron_diarization.py`: port
  `bench/run_nemotron_diarization.py` behind a small adapter class with
  `load()` and `diarize(audio_path) -> list[Turn]`. Load from
  `request.model_path` with `local_files_only=True`, run offline, threshold
  from options, labels `SPEAKER_00`… in arrival order.

**Verify**: protocol tests pass. Local-only gate (needs the GPU): run the runner
against `bench/out/test.16k.wav` through `launch_engine` and get Turns back.

### Step 5: Core adapter, factory, stage

- `engines/isolated_python.py`: `IsolatedPythonDiarizer(model_path, device,
  threshold)` with `load()` and `diarize(audio_path, min_speakers=None,
  max_speakers=None) -> DiarizationResult`. It launches the runner and drops
  speakers under `MIN_SPEAKER_SECONDS = 5.0` total (decision 7). It returns
  `DiarizationResult(turns, exclusive_turns=compute_exclusive_turns(turns),
  engine="nemotron-3-diarization")`.
- Move `compute_exclusive_turns` to `engines/overlap.py` (decision 8).
- `make_diarizer` branches on `run_config.diarization.engine`. pyannote
  gets `clustering` without the `engine` key (its override code would
  otherwise try to cast it to a float and warn).
- `PyannoteDiarizer.diarize` sets `engine="pyannote"` on its result.
- `tasks/diarization.py` records `result.engine or DIARIZER_ENGINE` in both
  paths (decision 11).

**Verify**: tests with a fake runner response cover the dropped phantom
speaker, the computed exclusive Turns, the factory branch, and the stored
`engine` for both single and dual track. Suite passes.

### Step 6: Health, queueing, settings payload

- `engines.diarizer_status(engine)` returns the same `EngineHealth` dict
  shape as `engine_status`. For Nemotron it runs the manifest probe with a
  synthetic preset
  `{"engine": "nemotron-3-diarization", "model_path": settings.nemotron_diarization_model_path, "device": "cuda"}`.
  For pyannote it reports `ready` when `pyannote.audio` is importable and
  the HF token is set.
- `api/meetings.py`: before queueing, probe the Diarizer the current
  Preferences select. A blocked one gets 409, like `_require_usable_preset`.
  Apply this to reprocessing too.
- `GET /api/settings` also returns
  `"diarizers": [{"id", "name", "description", **diarizer_status(id)}]` for
  both Engines, which plan 023 renders.

**Verify**: API tests for the 409 path and the `diarizers` payload. Suite passes.

### Step 7: Smoke tier and ADR

- Add `nemotron-3-diarization` to the opt-in smoke tests in
  `tests/engine_smoke/` (load + inference on `--engine-smoke-audio`).
- Write `docs/adr/0009-selectable-diarizer.md`. It records that the
  Diarizer is a Preference with two Engines, the pinned-Transformers-commit
  exception, and the bench numbers above.

**Verify**: `.\.venv\Scripts\python.exe -m pytest -q tests` passes. Local
gate: `.\.venv\Scripts\python.exe -m pytest -q tests/engine_smoke --run-engine-smoke --engine-smoke-preset nemotron-3-diarization --engine-smoke-audio bench\out\test.16k.wav`.

### Step 8: Local end-to-end (user's machine)

With the Preference set to `nemotron-3-diarization`, reprocess the Sinop
2026-09-22 Meeting and check that:

- its stored diarization has `engine == "nemotron-3-diarization"`;
- no Speaker without Segments was created;
- the host is still named from the mic track.

Leave this box unchecked and say so in the Outcome note if the executor has
no GPU.

## Done criteria

- [ ] Default Preferences still diarize with pyannote, and Step 1 tests pass unchanged.
- [ ] Selecting `nemotron-3-diarization` runs the isolated runtime, stores that Engine name, and drops sub-5 s speakers.
- [ ] A blocked Diarizer refuses queueing with 409; a failing runner fails the Job.
- [ ] `GET /api/settings` lists both Diarizers with health.
- [ ] Installers create the runtime and the local model snapshot; no Job downloads weights.
- [ ] ADR-0009 written.
- [ ] Local smoke tier and Step 8 end-to-end run on the user's machine.

## STOP conditions

- Drift check shows changes to the files in "Current state" that alter the
  functions named there.
- The pinned Transformers commit no longer installs or no longer exposes
  `nemotron3_diarization`. Report it; do not pick another commit on your own.
- Nemotron through the runner gives Turns that differ from
  `bench/run_nemotron_diarization.py` on the same file, beyond speaker label
  order.
- Any step would require a protocol field change (that is a schema bump,
  outside this plan).

## Outcome

_To be filled in by the executor._
