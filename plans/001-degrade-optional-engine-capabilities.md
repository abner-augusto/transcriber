# Plan 001: Degrade safely when optional Engine capabilities fail

> **Executor instructions**: Follow this plan step by step. Run every verification
> command before proceeding. If a STOP condition occurs, stop and report instead
> of broadening the change. Update Plan 001 in `plans/README.md` when done.
>
> **Drift check (run first)**:
> `git diff --stat 5fcd6a8..HEAD -- engines/vibevoice.py engines/qwen3_asr.py tests/test_engines.py`
> If these files changed, compare the current state below with the live code and
> stop on a semantic mismatch.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `5fcd6a8`, 2026-09-14

## Why this matters

Both Python Engines advertise proportional timestamp fallback, but an exception
while loading the optional Qwen forced aligner occurs before the guarded inference
block. A missing or incompatible aligner therefore aborts transcription after the
large primary model has loaded. The primary Transcriber must remain usable and
report degraded timestamp quality when only this optional capability fails.

## Current state

- `engines/vibevoice.py:268-278` loads `AutoProcessor` and
  `AutoModelForTokenClassification` without exception handling.
- `engines/vibevoice.py:409-415` catches aligner inference failures and then creates
  proportional timestamps, but cannot catch initialization failures.
- `engines/qwen3_asr.py:116-127` has the same unguarded initialization pattern.
- `engines/qwen3_asr.py:232-240` already defines proportional fallback.
- `tests/test_engines.py:386-480` tests protocol conformance, parsing, stitching,
  and shallow availability; it does not test aligner initialization failure.
- Domain constraint from `CONTEXT.md`: a Transcriber produces `Word` values and
  knows nothing about Speakers. Preserve leading-space `Word.text` semantics from
  `engines/ports.py:15-51`.
- ADR constraint from `docs/adr/0005-qwen3-asr-and-vibevoice-engines.md`: both
  Engines emit standard `Word` values; VibeVoice also exposes native Turns.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Focused tests | `.\venv\Scripts\python.exe -m pytest tests/test_engines.py -q` | all tests pass |
| Full backend tests | `.\venv\Scripts\python.exe -m pytest -q` | exit 0 |
| Diff check | `git diff --check` | exit 0, no errors |

## Scope

**In scope**:

- `engines/vibevoice.py`
- `engines/qwen3_asr.py`
- `tests/test_engines.py`

**Out of scope**:

- Dependency upgrades or edits to `requirements.txt`.
- Changes to the primary VibeVoice or Qwen model loading path.
- Replacing the proportional timestamp algorithm.
- UI health-state changes; Plan 004 owns them.

## Git workflow

- Branch: `advisor/001-optional-engine-fallback`
- Use small conventional commits, for example
  `fix(engines): degrade when forced aligner cannot load`.
- Do not push unless instructed.

## Steps

### Step 1: Add failing initialization regression tests

In `tests/test_engines.py`, monkeypatch the Transformers processor/model loaders so
the processor succeeds and the model loader raises the observed unknown
`qwen3_asr` architecture error. Cover both Transcribers. Assert that loading the
optional aligner does not raise, both aligner fields remain `None`, and a warning
identifies the Engine, aligner path, and proportional fallback.

Also test a generic load failure such as CUDA OOM so the behavior is not coupled
only to one exception string.

**Verify**: run the focused tests and confirm the new tests fail against the
unmodified adapters for the expected uncaught exception.

### Step 2: Contain optional aligner initialization failures

Guard each adapter's complete aligner initialization transaction. Assign processor
and model fields only after both loads succeed, or clear both fields on failure.
Record an `_aligner_unavailable_reason` (or equivalent) for later health reporting
and emit one warning per Transcriber instance. Do not catch failures from the
primary model loader.

Prevent repeated load attempts in the same Transcriber instance after a known
failure; otherwise every chunk could repeat an expensive deterministic error.

**Verify**: focused tests pass.

### Step 3: Lock down fallback output

Add a small test for each adapter proving that unavailable alignment still returns
ordered `Word` values with nondecreasing timestamps, join-ready text, and a lower
`alignment_score` than successful forced alignment. Mock primary inference; do not
load real weights or require CUDA.

**Verify**: focused tests pass, then run the full backend suite.

## Test plan

- Unknown architecture during aligner model load.
- Generic model-load failure.
- Processor-load failure.
- Failure warning emitted once per instance.
- Proportional fallback preserves text order and returns valid timestamps.
- Primary model failures continue to raise and fail the Job.

Use existing monkeypatch patterns in `tests/test_engines.py` and fake Engine style
from `tests/fakes.py`.

## Done criteria

- [ ] Both optional aligner loaders are transactional and exception-safe.
- [ ] A failed optional aligner cannot abort otherwise successful transcription.
- [ ] The degradation reason is available for diagnostics.
- [ ] Primary model load failures still propagate.
- [ ] Focused and full backend tests pass.
- [ ] Only in-scope files and `plans/README.md` changed.

## STOP conditions

- The aligner is found to be required for VibeVoice native diarization rather than
  only timestamps.
- A safe fallback requires changing the `Word` or `Transcriber` public contract.
- A test requires downloading model weights or contacting the network.

## Maintenance notes

Reviewers should verify that broad exception handling surrounds only the optional
capability. Plan 004 should expose `_aligner_unavailable_reason` as `degraded`
health without duplicating exception parsing.

