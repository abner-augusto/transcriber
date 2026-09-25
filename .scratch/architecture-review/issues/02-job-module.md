# 02 - One Job Module: Enqueue, Run, Progress, Recover

**Source:** architecture review 2026-09-24, candidate 4.

**What to build:** A Job module with a small interface — enqueue a Job for a
Meeting, run it with lifecycle handling, publish progress, subscribe to
progress, recover interrupted Jobs — with Celery + Redis as adapters behind it.

**Why:** The Job lifecycle is spread across `api/meetings.py` (three copies of
claim + enqueue), `tasks/shared.py` (`meeting_job`, `_fail_job`,
`update_progress`, `publish_event`, module-level Redis pool),
`database.py::recover_stale_jobs` called from API startup (fails live Jobs,
see plan 007), and `api/websocket.py` (knows the Redis channel name).

**Blocked by:** plan 007 (recovery moves to the worker). Plan 012 is done, and after
plan 013 `tasks/shared.py` holds only the lifecycle and persistence code this
module absorbs.
Plan 010 (dedupe enqueue) should be re-scoped into this ticket rather than
executed on its own.

**Status:** completed

**Plan:** `plans/017-job-module.md` (design session 2026-09-24 on 02/04/05).

**Outcome:** The adapters are Celery + Redis in production and inline + in-memory
for tests. `rebuild_speakers_and_segments` lives in `meeting_store.py`.
Progress messages retain the existing WebSocket JSON shape. Later adapter
choices remain in plans 019–020.

**Acceptance criteria (draft):**
- [x] All four Job routes enqueue through one function; the atomic `PROCESSING` claim exists once
- [x] `api/` and task bodies do not import `redis` or `celery` directly; those imports stay in adapter modules
- [x] Task tests use injected session factories and inline progress adapters, without patching `SessionLocal` or `publish_event`
- [x] Backend suite: 327 passed, 20 local Engine smoke tests skipped
