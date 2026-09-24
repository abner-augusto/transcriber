# 02 - One Job Module: Enqueue, Run, Progress, Recover

**Source:** architecture review 2026-09-24, candidate 4.

**What to build:** A Job module with a small interface — enqueue a Job for a
Meeting, run it with lifecycle handling, publish progress, subscribe to
progress, recover interrupted Jobs — with Celery + Redis as one adapter behind
it.

**Why:** The Job lifecycle is spread across `api/meetings.py` (three copies of
claim + enqueue), `tasks/shared.py` (`meeting_job`, `_fail_job`,
`update_progress`, `publish_event`, module-level Redis pool),
`database.py::recover_stale_jobs` called from API startup (fails live Jobs,
see plan 007), and `api/websocket.py` (knows the Redis channel name).

**Blocked by:** plan 007 (recovery moves to the worker), plan 012.
Plan 010 (dedupe enqueue) should be re-scoped into this ticket rather than
executed on its own.

**Status:** needs-exploration

**Open questions for the exploration session:**
- Which adapters are real? Proposed: Celery+Redis (today), local worker with
  the Job table as the queue (ticket 05), synchronous in-process (tests).
- Where does `rebuild_speakers_and_segments` go — Job module or a Meeting
  persistence module?
- Progress transport after Redis is gone: in-process broadcaster over the
  existing WebSocket, SSE, or polling the Job row?
- How are time limits expressed without Celery's soft/hard limits?

**Acceptance criteria (draft):**
- [ ] API routes enqueue through one function; the atomic `PROCESSING` claim exists once
- [ ] `tasks/` and `api/websocket.py` do not import `redis` or `celery` directly
- [ ] Task tests run through the synchronous adapter without monkeypatching `SessionLocal` / `publish_event`
