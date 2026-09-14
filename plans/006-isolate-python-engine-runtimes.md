# Plan 006: Isolate Python Engines in dedicated runtimes

> **Executor instructions**: Do not begin until Plans 001–005 are DONE. This is a
> staged migration; keep each commit runnable and run every gate. Update Plan 006
> in `plans/README.md` when complete.
>
> **Drift check (run first)**:
> `git diff --stat 5fcd6a8..HEAD -- engines tasks config.py install.ps1 install.sh start.ps1 start.sh requirements engine_runtimes tests docs/adr`
> Reconcile the completed contracts from Plans 001–005. Stop if any are absent.

## Status

- **Execution**: DONE
- **Priority**: P2
- **Effort**: L
- **Risk**: HIGH
- **Depends on**: Plans 001, 002, 003, 004, and 005
- **Category**: architecture
- **Planned at**: commit `5fcd6a8`, 2026-09-14

## Why this matters

Qwen, VibeVoice, PyAnnote, and other Python ML stacks evolve against different
versions of Transformers, Torch, tokenizers, and CUDA libraries. A single process
environment forces them into one dependency solution and lets imports or global
registrations interfere. Running Python Engines behind a versioned subprocess
protocol makes each Engine independently installable, testable, and replaceable,
matching the existing external-process shape of whisper.cpp and parakeet.cpp.

## Current state

- `engines/ports.py:98-108` defines the in-process `Transcriber` protocol returning
  `list[Word]`.
- `engines/__init__.py:98-122` constructs Qwen and VibeVoice adapters in the Celery
  process.
- `engines/vibevoice.py:29-44` mutates Transformers registration and `sys.path` at
  import time.
- `tasks/process_meeting.py:30-32` constructs all Engines in the shared worker.
- ADR 0005 requires Qwen to provide Words and VibeVoice to provide Words plus native
  `DiarizationResult`; preserve those outcomes.
- Plan 003 provides immutable runtime manifests; Plan 004 provides health states;
  Plan 005 provides load/inference smoke tests.

## Target boundary

The core process launches an Engine-specific Python executable with file-based JSON
request and response paths:

```text
core Celery worker
  -> <engine-python> -m engine_runners.<engine> --request request.json --response response.json
  <- response.json: schema_version, words, native_diarization, diagnostics, error
```

Use files rather than stdout for the protocol because upstream libraries write
progress and warnings to stdout/stderr. Logs remain diagnostic streams. Requests
must contain only local paths and configuration; ADR 0001 forbids remote processing.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Protocol tests | `.\venv\Scripts\python.exe -m pytest tests/test_engine_runtime_protocol.py -q` | all pass |
| Adapter tests | `.\venv\Scripts\python.exe -m pytest tests/test_engines.py -q` | all pass |
| Metadata suite | `.\venv\Scripts\python.exe -m pytest -m "not model_load and not model_inference" -q` | exit 0 |
| Runtime doctor | commands documented by Plans 003/005 | both runtimes ready or explicitly degraded |
| Frontend | `cd frontend; npm test; npm run build` | exit 0 |

## Scope

**In scope**:

- new `engine_runtimes/` protocol, launcher, and runner modules
- Qwen and VibeVoice adapter changes under `engines/`
- `engines/ports.py` serialization only if needed
- `config.py` and Preset/runtime configuration
- `install.ps1`, `install.sh`, `start.ps1`, `start.sh`
- runtime requirement/manifests from Plan 003
- Engine protocol, adapter, health, and smoke tests
- new ADR documenting process isolation
- installation and troubleshooting documentation

**Out of scope**:

- Whisper/parakeet protocol changes.
- Cloud inference, network APIs, or containers.
- Benchmark-quality changes to transcription or diarization.
- Running multiple GPU Engines concurrently.
- A generic plugin marketplace.

## Git workflow

- Branch: `advisor/006-isolate-engine-runtimes`
- Commit by migration stage. Suggested sequence:
  `feat(runtime): add versioned Engine subprocess protocol`,
  `refactor(vibevoice): run in isolated runtime`,
  `refactor(qwen): run in isolated runtime`, and
  `docs(architecture): record Engine runtime isolation`.
- Do not push unless instructed.

## Steps

### Step 1: Define and test protocol version 1

Create typed request/response serializers with strict schema versioning. Request
fields: Engine ID, audio path, vocabulary, model/aligner paths, device, and bounded
Engine options. Response fields: Words, optional native diarization, structured
diagnostics, runtime fingerprint, and structured error. Reuse `Word.from_dict` and
`Turn.from_dict`; reject nonfinite or unordered timestamps and paths outside the
request's declared local inputs/outputs.

**Verify**: protocol round-trip, malformed response, unknown version, timeout,
nonzero exit, and partial response tests pass using a fake runner.

### Step 2: Implement a safe runtime launcher

Resolve the Engine executable from the Plan 003 manifest/config, create request and
response files in a Meeting-scoped temporary directory, invoke with an argument
list (never a shell string), capture bounded diagnostics, enforce timeout and
cancellation, validate the response, and clean temporary protocol files in
`finally`. Preserve them only behind an explicit debug option that excludes audio.

**Verify**: fake subprocess tests cover spaces in Windows paths, timeout, crash,
malformed JSON, and cleanup.

### Step 3: Migrate VibeVoice first

Move imports and model execution that require VibeVoice/Torch/Transformers into the
VibeVoice runner. Keep parsing/stitching code where it can be tested without heavy
imports, or move it behind the protocol with equivalent unit coverage. The core
adapter launches the runner and returns Words plus native Turns exactly as before.
Remove import-time `sys.path` and AutoModel mutation from the core process.

**Verify**: unit/metadata tests pass, then VibeVoice load and inference smoke tests
pass in its dedicated environment.

### Step 4: Migrate Qwen3-ASR

Apply the same boundary to Qwen, preserving vocabulary, chunking, stitching, forced
alignment, and proportional fallback. Do not share the VibeVoice interpreter merely
because both use Transformers.

**Verify**: Qwen unit, load, and inference smoke tests pass in its runtime.

### Step 5: Build and verify runtime installers

Update platform installers to create `venv` for core plus deterministic Engine
environments such as `venv-engines/vibevoice` and `venv-engines/qwen3-asr`. Install
from immutable files, run `pip check`, then metadata doctor checks. Existing valid
environments should be reused only when their fingerprint matches; otherwise print
an explicit rebuild command.

**Verify**: fresh install in a disposable directory reconstructs both selected
runtimes and produces expected fingerprints.

### Step 6: Integrate health and Job diagnostics

Plan 004 probes the dedicated executable/environment rather than the core process.
Persist the runtime fingerprint and capability state in raw transcription Job
diagnostics so results can be traced to an exact environment. Keep blocked queue
gating and degraded warnings unchanged.

**Verify**: API/Job tests prove runtime mismatch blocks before queueing and completed
results contain the fingerprint without absolute secrets or environment dumps.

### Step 7: Document the architectural decision and remove compatibility code

Add an ADR explaining why Python ML Engines use isolated runtimes, the JSON boundary,
local-only guarantee, failure semantics, and how to add an Engine. Remove obsolete
shared-environment dependency copies and import hacks after both migrations pass.

**Verify**: `rg` finds no Qwen/VibeVoice imports from the core worker outside runner
and health modules; all test tiers pass.

## Test plan

- Strict request/response schema and version mismatch.
- Windows paths with spaces and Unicode.
- Runner timeout, crash, malformed/partial output, and cleanup.
- Word ordering/text contract and VibeVoice native Turns.
- Optional capability degradation crosses the subprocess boundary.
- Runtime fingerprint invalidation.
- Dedicated environment load/inference smoke for each Engine.
- Core test suite imports no heavyweight Engine package.

## Done criteria

- [ ] Core API/Celery environment does not import Qwen or VibeVoice runtime code.
- [ ] Qwen and VibeVoice execute with independently pinned interpreters.
- [ ] Protocol errors fail Jobs truthfully; optional failures remain degraded.
- [ ] Fast health probes and queue gates target the selected runtime.
- [ ] Runtime fingerprints are recorded with results.
- [ ] Fresh installation and all test tiers pass.
- [ ] ADR and platform docs match implementation.

## STOP conditions

- The completed Plan 001–005 contracts are absent or failing.
- A runner requires sending audio or transcript data over the network.
- Process isolation would force concurrent GPU model residency.
- The protocol needs arbitrary Python object serialization such as pickle.
- A migration cannot preserve existing Word/Turn output on the smoke fixture.

## Maintenance notes

Treat protocol and manifest versions as public internal APIs. Add fields compatibly
or bump the schema. Reviewers should scrutinize shell avoidance, path handling,
timeouts, cleanup, local-only behavior, and accidental heavy imports in core.
