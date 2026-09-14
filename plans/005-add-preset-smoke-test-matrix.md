# Plan 005: Add a tiered Preset smoke-test matrix

> **Executor instructions**: Complete Plans 003 and 004 first. Keep model-dependent
> tests opt-in and local. Update Plan 005 in `plans/README.md` when done.
>
> **Drift check (run first)**:
> `git diff --stat 5fcd6a8..HEAD -- engines engine_runtimes tests bench README.md`
> Stop if the health-result contract differs from Plan 004's documented shape.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW
- **Depends on**: `plans/003-pin-engine-runtime-dependencies.md`,
  `plans/004-probe-engine-health-before-queueing.md`
- **Category**: tests
- **Planned at**: commit `5fcd6a8`, 2026-09-14

## Why this matters

Unit tests proved that VibeVoice satisfied the `Transcriber` protocol while the
installed runtime could not load its configured aligner. The test strategy needs
three tiers: deterministic metadata tests on every run, opt-in model-load tests,
and opt-in tiny-audio inference tests. This catches dependency/checkpoint drift
without making ordinary tests download gigabytes or require a GPU.

## Current state

- `tests/test_engines.py:386-480` covers construction, protocol checks, parsing,
  stitching, and path existence only.
- `bench/run_vibevoice.py` and `bench/run_qwen3_asr.py` are benchmark scripts, not
  pass/fail installation checks.
- `test.mp3` exists but is not a minimal deterministic smoke fixture.
- There is no `.github/workflows/` directory and no documented local release gate.
- Backend focused Engine tests currently run with
  `.\venv\Scripts\python.exe -m pytest tests/test_engines.py -q`.

## Test tiers

1. `metadata`: no weights, network, or GPU; runs in the normal suite.
2. `load`: loads processor/model classes from local artifacts; opt-in.
3. `inference`: transcribes a tiny local fixture and validates the Engine port;
   opt-in and hardware-aware.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Metadata suite | `.\venv\Scripts\python.exe -m pytest -m "not model_load and not model_inference" -q` | exit 0 |
| Local load smoke | `.\venv\Scripts\python.exe -m pytest -m model_load --run-engine-smoke -q` | pass or explicit configured skip |
| Local inference smoke | `.\venv\Scripts\python.exe -m pytest -m model_inference --run-engine-smoke -q` | selected Engines pass |
| Frontend | `cd frontend; npm test` | all pass |

## Scope

**In scope**:

- `pytest.ini` or equivalent pytest configuration
- `tests/conftest.py`
- new `tests/engine_smoke/` tests and small audio fixture
- new `scripts/engine_doctor.py` or extension of the Plan 003 verifier
- `README.md` and platform installation guides
- optional lightweight `.github/workflows/ci.yml` for metadata/unit tests only

**Out of scope**:

- Committing model weights or recorded private Meeting audio.
- Running GPU/model tests in ordinary pull-request CI.
- Benchmark quality thresholds such as WER/WDER.
- Runtime isolation; Plan 006 owns it.

## Git workflow

- Branch: `advisor/005-engine-smoke-matrix`
- Suggested commits:
  `test(engines): add metadata and model smoke tiers` and
  `docs(engines): document runtime doctor checks`.

## Steps

### Step 1: Establish markers and opt-in controls

Register `model_load` and `model_inference` markers. Add an explicit
`--run-engine-smoke` option; without it, heavyweight tests must skip with a precise
reason. Let operators select Engines through a repeatable option or environment
variable. Reject unknown Engine names.

**Verify**: normal test collection has no unknown-marker warnings and performs no
model load.

### Step 2: Add metadata contract fixtures

Create tiny synthetic model directories containing representative `config.json`,
processor metadata, and fake shard indexes. Test every health check from Plan 004,
including the exact regression: Transformers below the required version plus
`model_type=qwen3_asr` must be `degraded` for an optional aligner or `blocked` for
a primary model.

**Verify**: metadata suite fails if compatibility checks are removed.

### Step 3: Add real local load smoke tests

Discover model paths only from configured Presets. For each selected Engine, run
the deep health/load operation against local files with network access disabled.
Load required components first and optional components separately so the report
names the failing capability. Release model objects and GPU memory between cases.

**Verify**: load command exits nonzero on a configured incompatible artifact and
reports the stable health check code.

### Step 4: Add tiny inference contract tests

Create or generate a short, redistributable WAV fixture with known speech or use a
documented synthetic fixture appropriate to each model. Validate only contract
properties: nonempty ordered Words, finite bounded timestamps, join-ready text,
and native Turns when advertised. Do not assert exact transcription wording across
hardware.

**Verify**: inference command passes on each installed Engine or explicitly skips
unselected/uninstalled Engines.

### Step 5: Expose a doctor command and release gate

Provide one command that prints package versions, runtime fingerprint, Preset
health, and optional smoke results in human-readable and JSON forms. Document it as
mandatory after dependency/model changes. If adding CI, run only unit and metadata
tiers with synthetic fixtures.

**Verify**: doctor JSON validates against a stable schema; normal CI/test path
downloads nothing.

## Test plan

- Marker opt-in and skip semantics.
- Metadata regression for unknown `qwen3_asr` architecture.
- Required versus optional component classification.
- Local-files-only model load.
- Port invariants for Words and native Turns.
- Cleanup after failed load and CUDA memory release where available.
- Doctor human and JSON output.

## Done criteria

- [ ] Normal tests catch metadata compatibility regressions without real weights.
- [ ] Heavy tests never run without explicit opt-in.
- [ ] Every shipped Preset can be selected for load and inference smoke tests.
- [ ] The doctor command returns nonzero for blocked Engines.
- [ ] No test contacts the network unless separately and explicitly enabled.
- [ ] Documentation states the exact commands and expected outcomes.

## STOP conditions

- A proposed fixture contains private Meeting content or copyrighted model data.
- Model loading cannot be made local-only.
- A test requires exact transcript text across GPU architectures.
- Normal unit tests begin allocating GPU memory or downloading artifacts.

## Maintenance notes

Any new Engine must add metadata fixtures and opt-in load/inference cases before its
Preset becomes selectable. Quality benchmarks remain under `bench/`; smoke tests
verify operability, not model accuracy.

