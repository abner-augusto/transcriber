# Plan 002: Make Celery task failures truthful

> **Executor instructions**: Execute each step and verification gate. Update Plan
> 002 in `plans/README.md` when complete.
>
> **Drift check (run first)**:
> `git diff --stat 5fcd6a8..HEAD -- tasks/process_meeting.py tasks/reprocess_task.py tasks/shared.py tests`
> Stop if the Job lifecycle or task exception structure changed materially.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: MED
- **Depends on**: none
- **Category**: correctness
- **Planned at**: commit `5fcd6a8`, 2026-09-14

## Why this matters

`meeting_job` correctly marks the domain Job and Meeting as failed, but the Celery
task catches the reraised exception and returns `{"error": ...}`. Celery therefore
logs `succeeded`, which contradicts application state and prevents normal worker
failure monitoring. Domain and transport status must agree.

## Current state

- `tasks/shared.py:86-125` owns `RUNNING`, `COMPLETED`, and `FAILED` transitions;
  after `_fail_job`, it reraises the original exception.
- `tasks/process_meeting.py:177-181` catches that exception and returns an error
  dictionary, converting Celery failure into success.
- Inspect `tasks/reprocess_task.py` for the same outer pattern and handle it
  consistently.
- `models/job.py:17-22` defines the domain status enum.
- Existing task integration tests use an in-memory database in
  `tests/test_pyannote_exclusive.py:268-345`.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Task tests | `.\venv\Scripts\python.exe -m pytest tests/test_pyannote_exclusive.py tests/test_dual_track.py -q` | all pass |
| Full backend | `.\venv\Scripts\python.exe -m pytest -q` | exit 0 |
| Diff check | `git diff --check` | exit 0 |

## Scope

**In scope**:

- `tasks/process_meeting.py`
- `tasks/reprocess_task.py` only if it has the same conversion
- `tasks/shared.py` only if a narrow lifecycle helper is required
- one new or existing task-focused test file under `tests/`

**Out of scope**:

- Automatic retries or retry policy.
- Changes to WebSocket event payloads.
- Engine fallback behavior.
- Database schema changes.

## Git workflow

- Branch: `advisor/002-truthful-celery-failures`
- Suggested commit: `fix(tasks): preserve Celery failure state`.

## Steps

### Step 1: Characterize failed task behavior

Create a task integration test using the existing in-memory database pattern. Make
`make_transcriber` return an Engine that raises `RuntimeError("engine failed")`.
Assert that the task call raises, while the persisted Job and Meeting are both
`FAILED`, `job.error` contains the message, and the Redis error event is published.

**Verify**: the new test fails because the current task returns an error dict.

### Step 2: Remove exception-to-success conversion

Let exceptions already processed by `meeting_job` propagate to Celery. Keep special
handling only when it adds context without changing failure semantics. Apply the
same rule to reprocessing tasks.

Do not call `_fail_job` twice. `meeting_job` remains the sole lifecycle owner.

**Verify**: task tests pass.

### Step 3: Verify success remains unchanged

Add or retain an assertion that a successful task returns its completed result and
persists `COMPLETED`. Confirm no error event is emitted.

**Verify**: task tests and full backend suite pass.

## Test plan

- Primary Engine raises during a processing Job.
- Reprocessing failure, if the same catch exists.
- Database states and published event remain correct after propagation.
- Successful tasks still return normally.
- No retry behavior is introduced implicitly.

## Done criteria

- [ ] Celery sees genuine processing exceptions as failures.
- [ ] Domain Job and Meeting remain marked `FAILED` before propagation.
- [ ] Each failure is persisted and published once.
- [ ] Existing successful task behavior is unchanged.
- [ ] Task-focused and full backend tests pass.

## STOP conditions

- Existing callers depend on receiving an error dictionary from direct task calls.
- Celery configuration automatically retries all raised exceptions.
- Correct propagation requires changing public API response schemas.

## Maintenance notes

If retries are added later, define idempotency and retryable exception classes
explicitly. Do not reintroduce return-value errors to suppress worker failures.

