# Plan 007: Recover interrupted Jobs on the Celery worker, not the API

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 40b455a..HEAD -- database.py main.py tasks/celery_app.py api/meetings.py tests/test_task_failure_lifecycle.py tests/test_meeting_api.py tests/test_model_settings_api.py tests/conftest.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `40b455a`, 2026-09-17

## Outcome (2026-09-24)

Done in `ba6c010`, as one commit because the characterization tests encode
the fixed behavior. Beyond the plan, `tests/test_job_recovery.py` also fires
Celery's `worker_ready` signal and asserts recovery runs, instead of relying
only on the source-text checks in step 4.

After review, the `TRANSCRIBER_TESTING` switch in FastAPI startup was replaced
by an autouse fixture in `tests/conftest.py` that stubs
`cleanup_orphaned_storage`, and the `celery_app` text check was dropped (the
signal test covers it).

The deferred lost-PENDING case (see "Maintenance notes") is tracked in
`.scratch/architecture-review/issues/10-lost-pending-jobs.md`; plan 019
removes it for good.

## Why this matters

Job recovery currently runs in FastAPI startup. The Celery worker is a
separate process. Restarting the API (a second terminal, or `uvicorn --reload`
in `README.md` / `start.sh`) marks in-flight Jobs `FAILED` and Meetings
`FAILED` while the worker is still writing results. Because
`start_processing` only rejects `PROCESSING`, the user can Retry and queue a
second Job on the same Meeting.

The inverse is also wrong: if the worker dies, Jobs stay `RUNNING` until
someone restarts the API. `TestClient(app)` triggers the same startup, so
pytest can fail live Jobs and walk `./storage` via the real `SessionLocal`.

## Current state

- `database.py` — `recover_stale_jobs` fails both `RUNNING` and `PENDING`;
  `cleanup_orphaned_storage` deletes storage dirs whose names are not meeting
  IDs. Both use `SessionLocal()`, not the FastAPI `get_db` override.
- `main.py:43-47` — FastAPI `@app.on_event("startup")` always calls
  `init_db()`, `recover_stale_jobs()`, `cleanup_orphaned_storage()`.
- `api/meetings.py:248-265` — `start_processing` blocks only when status is
  already `PROCESSING`. After recovery sets `FAILED`, Retry is allowed.
- `tasks/celery_app.py` — Celery app, `include=["tasks.process_meeting",
  "tasks.reprocess_task"]`, `worker_prefetch_multiplier=1`. No worker
  signals. Production start is `celery -A tasks.celery_app worker --pool=solo`
  (single worker).
- `models/job.py:18-22` — `JobStatus` has `CANCELLED`; unused. Do not
  implement user-facing cancel here.
- `tests/test_task_failure_lifecycle.py` — sqlite + monkeypatch
  `tasks.shared.SessionLocal`; pattern for isolated Job tests.
- `tests/test_meeting_api.py:48` and `tests/test_model_settings_api.py:9` —
  `TestClient(app)` runs startup against settings.`database_url`.
- Domain terms from `CONTEXT.md`: **Job** is one unit of background
  processing over a Meeting (avoid "task" except for the Celery mechanism).
  **Meeting** status `PROCESSING` means a Job is in flight.

Excerpts:

```python
# database.py:57-83
def recover_stale_jobs():
    """Mark any jobs stuck in RUNNING/PENDING as FAILED on startup.
    ...
    """
    stale_jobs = db.query(Job).filter(
        Job.status.in_([JobStatus.RUNNING, JobStatus.PENDING])
    ).all()
    for job in stale_jobs:
        job.status = JobStatus.FAILED
        job.error = "Task interrupted by server restart. Please retry."
        ...
        if meeting and meeting.status == MeetingStatus.PROCESSING:
            meeting.status = MeetingStatus.FAILED
```

```python
# main.py:43-47
@app.on_event("startup")
def startup():
    init_db()
    recover_stale_jobs()
    cleanup_orphaned_storage()
```

Repo conventions: Job failure persistence is already truthful via
`meeting_job` in `tasks/shared.py` (see `tests/test_task_failure_lifecycle.py`).
Match that sqlite-sessionmaker pattern. Commit style from history:
`fix(startup): ...`, `test: ...`.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| New recovery tests | `.\venv\Scripts\python.exe -m pytest tests/test_job_recovery.py -q` | all pass |
| Task lifecycle tests | `.\venv\Scripts\python.exe -m pytest tests/test_task_failure_lifecycle.py tests/test_meeting_api.py -q` | all pass |
| Ordinary backend suite | `.\venv\Scripts\python.exe -m pytest -m "not model_load and not model_inference" -q` | exit 0 |
| Diff whitespace | `git diff --check` | exit 0, no errors |

## Suggested executor toolkit

- If the `tdd` skill is available, use it for steps 1–3 (red, then green).
- Read `CONTEXT.md` Job / Meeting terms before naming anything.

## Scope

**In scope** (the only files you should modify):

- `database.py`
- `main.py`
- `tasks/celery_app.py`
- `tests/test_job_recovery.py` (create)
- `tests/conftest.py`
- `tests/test_model_settings_api.py` (only if module-level `TestClient(app)`
  still constructs during import after the startup guard; prefer the guard
  so this file can stay unchanged)

**Out of scope**:

- User-facing Job cancellation (`JobStatus.CANCELLED`).
- `acks_late`, retries, or changing Celery time limits.
- Deleting a Meeting while a Job runs (do not add `revoke` here).
- Skipping `init_db()` in tests (known leftover; do not expand).
- Any file under `engines/`, `engine_runtimes/`, `install.ps1`.
- Frontend.

## Git workflow

- Branch: `advisor/007-job-recovery-on-worker`
- Commits: `test: characterize interrupted job recovery` then
  `fix: recover running jobs on celery worker start`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Characterization tests for today's recover function

Create `tests/test_job_recovery.py` modeled on
`tests/test_task_failure_lifecycle.py:_database` (sqlite file, sessionmaker,
no Postgres).

Monkeypatch `database.SessionLocal` (the name `recover_stale_jobs` actually
uses) to the sqlite factory.

Cover, against the **current** implementation, then keep the assertions that
must remain true after the fix. Write the tests so the post-fix behavior is
what they encode; the first run of the PENDING case should fail today's
code, which is the point:

1. A `RUNNING` Job whose Meeting is `PROCESSING` becomes `FAILED` with a
   non-empty `error` and `completed_at` set; Meeting becomes `FAILED`.
2. A `PENDING` Job is **left `PENDING`**; its Meeting is **not** forced to
   `FAILED`. (Today this fails — that is the bug. After step 2 it must pass.)
3. `COMPLETED` Jobs and Meetings are untouched.
4. Two RUNNING Jobs for two Meetings: both recovered independently.

Do not import `main.app` in this file (that would run startup).

**Verify**: `.\venv\Scripts\python.exe -m pytest tests/test_job_recovery.py -q`
→ test 2 fails on current code (`PENDING` was incorrectly failed). Tests 1,
3, 4 may pass already. If test 1 cannot even import `recover_stale_jobs`
without Postgres, STOP.

### Step 2: Recover only RUNNING Jobs, and only from the worker

In `database.py`:

- Keep the function in `database.py` (callers stay simple).
- Filter **only** `JobStatus.RUNNING` (not `PENDING`).
- Error text: `"Job interrupted by worker restart. Please retry."`
- Still set `job.completed_at` and flip the Meeting to `FAILED` only when
  `meeting.status == MeetingStatus.PROCESSING`.
- Leave `cleanup_orphaned_storage` behavior unchanged except the test guard
  in step 4.

In `main.py` `startup()`:

- Keep `init_db()`.
- **Remove** the `recover_stale_jobs()` call.
- Keep `cleanup_orphaned_storage()`, but skip it when
  `os.environ.get("TRANSCRIBER_TESTING")` is a non-empty string.

In `tasks/celery_app.py`:

- After `celery_app` is created, connect Celery's `worker_ready` signal to
  `database.recover_stale_jobs`. Import the function **inside** the signal
  handler to avoid import cycles at module load.
- Assumption to document in a one-line comment: this deployment runs a
  single `--pool=solo` worker. Do not call Celery inspect.

```python
from celery.signals import worker_ready

@worker_ready.connect
def _recover_interrupted_jobs(**kwargs):
    from database import recover_stale_jobs
    recover_stale_jobs()
```

**Verify**: `.\venv\Scripts\python.exe -m pytest tests/test_job_recovery.py -q`
→ all pass, including the PENDING case.

### Step 3: Guard pytest away from storage cleanup

In `tests/conftest.py` `pytest_configure` (already exists), set
`os.environ["TRANSCRIBER_TESTING"] = "1"` as the first line so it is in
place before collection constructs any `TestClient`.

Confirm `main.py` startup skips `cleanup_orphaned_storage` when that env
var is set. Do not skip `init_db`.

**Verify**: `.\venv\Scripts\python.exe -m pytest tests/test_meeting_api.py tests/test_model_settings_api.py tests/test_vocabulary_profiles.py -q`
→ still pass.

### Step 4: Assert API startup no longer recovers Jobs

In `tests/test_job_recovery.py` add a source assertion that does not boot
the app against Postgres:

```python
from pathlib import Path

def test_fastapi_startup_does_not_call_recover_stale_jobs():
    text = Path("main.py").read_text(encoding="utf-8")
    assert "recover_stale_jobs()" not in text
```

And assert the worker module wires the signal:

```python
def test_celery_app_registers_worker_ready_recovery():
    text = Path("tasks/celery_app.py").read_text(encoding="utf-8")
    assert "worker_ready" in text
    assert "recover_stale_jobs" in text
```

**Verify**: `.\venv\Scripts\python.exe -m pytest tests/test_job_recovery.py -q` → all pass.

## Test plan

- New file `tests/test_job_recovery.py` as in steps 1 and 4.
- Pattern: `tests/test_task_failure_lifecycle.py` (sqlite, monkeypatch
  `SessionLocal`, no GPU, no Redis).
- Existing `tests/test_task_failure_lifecycle.py` must still pass: worker
  crash recovery is separate from in-task `_fail_job`.
- Verification: `.\venv\Scripts\python.exe -m pytest -m "not model_load and not model_inference" -q` → exit 0.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `.\venv\Scripts\python.exe -m pytest tests/test_job_recovery.py -q` exits 0
- [ ] `.\venv\Scripts\python.exe -m pytest -m "not model_load and not model_inference" -q` exits 0
- [ ] `rg "recover_stale_jobs" main.py` returns no matches
- [ ] `rg "worker_ready" tasks/celery_app.py` matches
- [ ] `recover_stale_jobs` in `database.py` filters only `JobStatus.RUNNING`
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `plans/README.md` status row for 007 updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- A step's verification fails twice after a reasonable fix attempt.
- Wiring `worker_ready` requires importing FastAPI, engines, or GPU stacks
  into `tasks/celery_app.py`.
- You find more than one Celery worker configured in start scripts
  (`--concurrency` > 1, or multiple worker processes). The RUNNING-only
  recover-all assumption would be wrong.
- The fix appears to require `celery.control.inspect` or `acks_late`.
- You need to touch `engines/` or `api/meetings.py`.

## Maintenance notes

- If a second Celery worker is ever added, this recover-all-RUNNING
  approach will steal in-flight Jobs from the other worker. Switch to
  inspecting active `celery_task_id`s before failing anything.
- PENDING Jobs whose broker message was lost (worker crash before
  `meeting_job` sets RUNNING, default Celery ack-on-receive) can stay
  PENDING forever. That edge is deferred; do not fail PENDING to "fix" it.
- Reviewer should check: API restart with a live worker must not flip
  Meetings to FAILED; pytest must not delete `storage/` dirs.
- Plan 010 may add an enqueue helper in `api/meetings.py`; it must keep
  the `PROCESSING` claim so Retry cannot overlap a still-running worker
  Job. After this plan, that claim is again a reliable lock.
