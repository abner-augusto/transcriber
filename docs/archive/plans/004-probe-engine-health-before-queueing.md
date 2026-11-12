# Plan 004: Probe Engine health before queueing Jobs

> **Executor instructions**: Complete Plan 003 first. Run every verification gate
> and update Plan 004 in `plans/README.md` when done.
>
> **Drift check (run first)**:
> `git diff --stat 5fcd6a8..HEAD -- engines api/meetings.py api/model_settings.py frontend/src tests`
> Compare the runtime-manifest API from Plan 003 with this plan and stop if it does
> not expose package and checkpoint compatibility rules.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: `plans/003-pin-engine-runtime-dependencies.md`
- **Category**: correctness
- **Planned at**: commit `5fcd6a8`, 2026-09-14

## Why this matters

The current `engine_status()` returned `available: true` for a VibeVoice Preset
whose forced-aligner architecture the installed Transformers could not recognize.
The API then queued the Job without rechecking runtime health. A fast, structured
probe must distinguish a usable Engine, a usable Engine with optional degradation,
and a blocked Engine, and the queue boundary must enforce that result.

## Current state

- `engines/__init__.py:131-175` checks only imports and primary model-path
  existence for Qwen/VibeVoice.
- `api/model_settings.py:36-43` merges this shallow status into each Preset.
- `api/meetings.py:232-255` creates and queues a Job without calling
  `engine_status()`.
- `frontend/src/pages/HomePage.tsx:430-440` disables unavailable Presets, but the
  default option and direct API requests can still reach the queue boundary.
- `frontend/src/components/DuplicateReprocessDialog.tsx:18-68` labels unavailable
  Presets but can select them.
- `tests/test_engines.py:466-480` considers any existing Qwen model directory
  available.
- Preserve domain terms: a Preset selects an Engine; processing creates a Job for
  a Meeting. Do not call a Celery task a Job in UI or API messages.

## Target contract

Define a serializable result equivalent to:

```python
EngineHealth(
    state="ready" | "degraded" | "blocked",
    summary=str,
    checks=list[EngineCheck],
    fingerprint=str,
)
```

Each check has a stable code, required/optional severity, pass/fail state, and
actionable message. `available` may remain temporarily as
`state != "blocked"` for frontend compatibility.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Backend health tests | `.\venv\Scripts\python.exe -m pytest tests/test_engine_health.py tests/test_model_settings_api.py -q` | all pass |
| API/task tests | `.\venv\Scripts\python.exe -m pytest tests/test_dual_track.py tests/test_pyannote_exclusive.py -q` | all pass |
| Frontend tests | `cd frontend; npm test` | all pass |
| Frontend build | `cd frontend; npm run build` | exit 0 |
| Full backend | `.\venv\Scripts\python.exe -m pytest -q` | exit 0 |

## Scope

**In scope**:

- new `engines/health.py`
- `engines/__init__.py`
- `api/model_settings.py`
- `api/meetings.py`
- `frontend/src/api.ts`
- `frontend/src/pages/HomePage.tsx`
- `frontend/src/components/SettingsDialog.tsx`
- `frontend/src/components/DuplicateReprocessDialog.tsx`
- new `tests/test_engine_health.py`
- relevant API/frontend tests

**Out of scope**:

- Loading full model weights in normal GET requests.
- Installing or repairing packages from the health probe.
- Runtime subprocess isolation.
- Automatic fallback to a different Preset without user choice.

## Git workflow

- Branch: `advisor/004-engine-health-gate`
- Suggested commits:
  `feat(engines): add structured health probes`,
  `fix(api): reject blocked Engine Jobs`, and
  `feat(frontend): show degraded Engine capabilities`.

## Steps

### Step 1: Build pure metadata probes

Implement `probe_engine(preset, deep=False)` using the Plan 003 manifest. Without
loading weights, verify the Engine package/version, exact required class imports,
primary model config, declared shard files, optional aligner config, requested
device, and CUDA availability. Read local JSON with normal file APIs; do not use
`from_pretrained()` in the fast path.

Compute a fingerprint from manifest runtime ID, package versions, model config
hashes, device, and relevant driver/runtime facts. Cache only by fingerprint.

**Verify**: fixture-based health tests pass without CUDA or real models.

### Step 2: Classify required and optional failures

Primary Engine failures produce `blocked`. Optional aligner failures produce
`degraded` with explicit fallback behavior. Successful required and optional checks
produce `ready`. Preserve a compatibility `available` field until all frontend
consumers migrate.

**Verify**: test all three states and stable check codes.

### Step 3: Enforce health at mutation boundaries

Before setting a default Preset, creating/updating a Preset response, duplicating a
Meeting for reprocessing, or queueing full processing, probe the resolved Preset.
Reject `blocked` with HTTP 409 and the structured failure summary. Permit
`degraded`, but persist or return its warning so the user knows timestamps will be
approximate.

The queue endpoint is authoritative even if the UI already disabled a Preset.

**Verify**: API tests prove blocked Jobs are not created or queued, degraded Jobs
are permitted, and ready Jobs remain unchanged.

### Step 4: Render health states in the frontend

Update TypeScript types and all Preset selectors. Disable blocked options, allow
degraded options with a visible warning, and never auto-select a blocked Preset.
Show individual checks in Settings without exposing stack traces.

**Verify**: frontend tests and build pass.

## Test plan

- Missing package, wrong package version, and missing required class.
- Missing model directory, malformed config, unsupported model type, missing shard.
- CUDA requested but unavailable.
- Optional aligner incompatibility returns `degraded`.
- Queue gate creates no Job for `blocked`.
- Direct API calls cannot bypass the gate.
- Duplicate dialog does not select a blocked Preset.
- Fingerprint invalidates cached health when package/config/device changes.

## Done criteria

- [ ] Every Preset receives `ready`, `degraded`, or `blocked` health.
- [ ] Fast probes never load model weights or use the network.
- [ ] Blocked Presets cannot create processing Jobs through any API path.
- [ ] Optional capability failures are visible but usable.
- [ ] Frontend and backend tests pass.
- [ ] Existing `available` clients remain compatible or are migrated atomically.

## STOP conditions

- A fast probe cannot determine required class/model compatibility without loading
  weights; move that check to Plan 005 instead of making GET requests expensive.
- The Plan 003 manifest cannot represent required versus optional dependencies.
- Queue gating would require silently changing a Meeting's selected Preset.

## Maintenance notes

Stable check codes are API surface. Add new checks rather than parsing exception
messages in the frontend. Never let the probe mutate packages, model files, or GPU
state.

