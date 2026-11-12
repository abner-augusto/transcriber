# Plan 017: One Job module (Celery as its first adapter)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. On a
> STOP condition, stop and report. When done, update `plans/README.md` and
> `.scratch/architecture-review/issues/02-job-module.md`.
>
> **Drift check (run first)**: `git diff --stat 284603d..HEAD -- api/meetings.py api/websocket.py tasks/ database.py main.py models/job.py tests/task_harness.py tests/test_task_failure_lifecycle.py tests/test_job_recovery.py`

## Status

- **Implementation**: DONE (backend suite passes; frontend unchanged)

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: plan 007 (done). Absorbs plan 010 (marked REJECTED:
  absorbed). If plan 014 is in flight, its new Reprocessing route must use
  `jobs.enqueue` after this lands.
- **Category**: architecture (deepening), first step of the stack migration
- **Planned at**: commit `284603d`, 2026-09-24
- **Source**: design session 2026-09-24 on tickets 02/04/05

## Where this sits

Stack migration decided on 2026-09-24 (single user, one machine, one GPU,
Windows native with Docker Desktop only for Postgres/Redis):

1. **017 (this plan)** — Job module; Celery + Redis become one adapter.
2. **018** — SQLite + FTS5, and a one-shot migration command.
3. **019** — local Job runner, one child process per Job; Celery and Redis
   no longer used.
4. **020** — remove Redis/Celery/Postgres/Docker, adopt `uv`, serve the built
   frontend, one start command.

Each step ships on its own and leaves the app working.

## Why this matters

A Job's lifecycle is spread over `api/meetings.py` (three copies of the
PROCESSING claim + Job insert + `.delay` + `celery_task_id`),
`tasks/shared.py` (`meeting_job`, `_fail_job`, `update_progress`,
`publish_event` and a module-level Redis pool), `database.py::recover_stale_jobs`
wired from `tasks/celery_app.py`, and `api/websocket.py` (knows the Redis
channel name). Celery and Redis leak into all of them, so replacing them in
plan 019 would touch every one.

## Decisions (do not re-litigate)

- The Job module owns: enqueue (the atomic claim), run (lifecycle: RUNNING →
  COMPLETED/FAILED, error event), progress (persist + publish), subscribe
  (progress stream for one Meeting), recover (fail interrupted RUNNING Jobs).
- Adapters behind it: **Celery+Redis** now; **local runner** in plan 019;
  **inline** (synchronous, in-process publisher) for tests.
- Progress messages keep today's exact JSON shape on the WebSocket.
- `rebuild_speakers_and_segments` is Meeting persistence, not Job lifecycle:
  it moves to `meeting_store.py` (or similar), not into the Job module.

## Target interface

```python
# jobs/__init__.py
def enqueue(db, meeting_id: str, kind: JobType) -> Job
    # 404 if missing, JobAlreadyRunning if the atomic PROCESSING claim fails,
    # inserts a PENDING Job, hands it to the runner adapter
@contextmanager
def running(meeting_id: str, job_id: str) -> Iterator[tuple[Session, Meeting, Job]]
    # today's meeting_job, unchanged behavior
def progress(db, job, meeting, percent: float, step: str) -> None
def subscribe(meeting_id: str) -> AsyncIterator[dict]
def recover() -> None

# jobs/runners.py  — the seam
class JobRunner(Protocol):
    def submit(self, job: Job) -> str | None     # returns an external id (celery task id) or None
class ProgressBus(Protocol):
    def publish(self, meeting_id: str, event: dict) -> None
    def subscribe(self, meeting_id: str) -> AsyncIterator[dict]
```

The active adapters are chosen once at startup (config), not per call.
Task bodies (`tasks/process_meeting.py`, `tasks/reprocess_task.py`) become
plain functions `(meeting_id, job_id)`; the Celery adapter wraps them.

## Steps

1. **Characterize**: API tests for the three enqueue routes (claim rejects a
   second request with 400, Job row inserted, runner called once), and a
   WebSocket test that a published event reaches a subscriber in today's
   shape. Use the inline adapters where Redis would be needed; add them
   first if required.
2. **Move lifecycle** from `tasks/shared.py` into `jobs/` (verbatim), and
   `rebuild_speakers_and_segments` into the Meeting persistence module.
3. **One enqueue**: the three routes call `jobs.enqueue`. Preset health
   checks stay in the routes that need them.
4. **Adapters**: Celery runner + Redis bus; inline runner + in-memory bus.
   `api/websocket.py` uses `jobs.subscribe`; `tasks/celery_app.py` registers
   the task bodies and keeps `worker_ready → jobs.recover`.
5. **Tests**: `tests/task_harness.py` switches to the inline adapters and
   stops monkeypatching `SessionLocal` / `publish_event` where the module
   now takes a session factory.

## Done criteria

- [x] `rg "\.delay\(|celery_task_id" api` returns nothing
- [x] `rg "import redis|from celery|celery_app" api tasks/process_meeting.py tasks/reprocess_task.py jobs/__init__.py` returns nothing (only `jobs/runners*.py` and `tasks/celery_app.py`)
- [x] The PROCESSING claim exists once
- [x] Backend suite passes; frontend unchanged
- [x] `plans/README.md`: 017 DONE, 010 REJECTED (absorbed)

Outcome: the Celery and Redis adapters remain the active production adapters.
The full backend test suite passed (327 passed, 20 local Engine smoke tests
skipped); no frontend files changed.

## STOP conditions

- The WebSocket message shape would have to change.
- The inline adapter cannot run the real task bodies without Celery imported.
