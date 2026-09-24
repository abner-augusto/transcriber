# Plan 019: Local Job runner, one child process per Job

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. On a
> STOP condition, stop and report. When done, update `plans/README.md` and
> `.scratch/architecture-review/issues/04-per-job-child-process.md`.
>
> **Drift check (run first)**: compare `jobs/`, `tasks/`, `engines/gpu_memory.py`,
> `main.py`, `api/websocket.py` against the end state of plans 017 and 018.

## Status

- **Priority**: P2
- **Effort**: L
- **Risk**: HIGH (process model on Windows `spawn`)
- **Depends on**: plans 017 and 018
- **Planned at**: commit `284603d`, 2026-09-24
- **Source**: design session 2026-09-24 on tickets 02/04/05

## Decisions (do not re-litigate)

1. **One Python process**: the FastAPI app plus a runner thread that takes the
   oldest PENDING Job from the Job table and runs it in a **child process**
   (`multiprocessing`, spawn start method; one Job at a time).
2. The child writes results to SQLite with its own session. It sends progress
   events to the parent over a `multiprocessing` queue; the parent persists
   progress on the Job row and publishes to an in-process `ProgressBus`.
3. The WebSocket endpoint and its message shape stay exactly as they are.
4. **Time limit**: the parent kills the child after
   `max(60 min, 3 × audio duration)`; the Job fails with a message naming the
   limit. The duration comes from the Meeting (known after extraction; use
   60 min until then).
5. **Restart semantics**: on startup, RUNNING Jobs are failed ("interrupted by
   restart", plan 007 rule); PENDING Jobs resume in creation order.
6. **VRAM**: child exit frees it. `engines/gpu_memory.py`,
   `unload_all_engines`, and every `unload()` / `release_gpu_memory()` call in
   the pipeline are deleted (the Transcriber port's `unload()` from plan 015
   goes too, if 015 landed).
7. A native crash in the child fails that Job and leaves the app running.
8. A user-facing Cancel is ticket 09, not this plan (the runner should expose
   `cancel(job_id)` internally so ticket 09 is only UI + route).

## Target interface

Adapters for the plan 017 seam: `LocalRunner` (thread + child process) and
`InProcessBus` (asyncio fan-out to WebSocket subscribers, thread-safe publish
from the runner thread). Selected in `main.py` startup; Celery adapters stay
in the tree until plan 020 deletes them.

## Steps

1. **Measure first**: on the user's machine, model load time per Job for
   parakeet.cpp (already a subprocess), faster-whisper large-v3, pyannote,
   and ECAPA. Record here. If per-Job loading adds more than ~60 s to a
   typical Job, STOP and report.
2. `InProcessBus` + tests (publish from a thread, two subscribers, unsubscribe
   on disconnect).
3. `LocalRunner`: claim loop over the Job table, child spawn, progress queue,
   timeout kill, crash handling, restart semantics. Tests with a fake Job body
   (success, raise, `os._exit(1)`, sleep past a tiny timeout).
4. Switch the app to the local adapters; the Celery worker is no longer
   started by `start.ps1` / `start.sh`.
5. Delete GPU unload machinery (decision 6).
6. On the user's machine: a real Job end to end for parakeet.cpp and
   faster-whisper large-v3; VRAM returns to idle baseline after each
   (`nvidia-smi`); restart the app mid-Job and confirm the rules in decision 5.

## Done criteria

- [ ] App runs with no Redis and no Celery process
- [ ] Child crash / timeout / restart behave as decided, with tests
- [ ] No `unload`/`release_gpu_memory` calls remain in the pipeline
- [ ] Measurements and the end-to-end check recorded in this plan

## STOP conditions

- Per-Job model loading cost is unacceptable (step 1).
- Windows `spawn` cannot import the task bodies without importing FastAPI or
  starting the server in the child.
- SQLite write contention between parent and child causes `database is locked`
  errors that `busy_timeout` does not absorb.
