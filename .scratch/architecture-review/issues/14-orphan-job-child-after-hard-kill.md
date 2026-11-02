# 14 - A Hard-Killed App Leaves Its Job Child Running

**Source:** plan 019 Step 6 machine check, 2026-11-02 (GPU window), on a fresh
checkout (`transcriber-cleaninstall`) with a snapshot of the local database.

**What happened:** with Job A (4 min of audio, faster-whisper large-v3) RUNNING
and Job B (Parakeet) PENDING, the app process (the uvicorn Python that owns
port 8000) was killed with `Stop-Process -Force`. On Windows the Job child
(`multiprocessing.spawn`, parent pid = the killed app) is not killed with
its parent:

1. Five seconds after the kill, the child was still alive and the GPU held
   4,624 MiB (idle baseline 449 MiB).
2. The restarted app ran startup recovery: Job A got
   `error = "Job interrupted by an application restart. Please retry."` and
   the Meeting went to `failed`. Then it started Job B.
3. The orphan and Job B's child ran on the GPU at the same time (8,514 MiB).
4. The orphan finished Job A and wrote its result over the recovery: Job A ended
   `status = COMPLETED` **with** the restart error still set, and the Meeting
   ended `completed` with 23 Segments.
5. Job B completed. Once both children exited, the GPU went back to 449 MiB.

**Why it matters:** decision 5 of plan 019 (RUNNING work fails on restart)
does not hold after a hard kill. Two Jobs share the GPU, which the runner
exists to prevent. The Job row ends up contradictory (COMPLETED with an
interruption error).

**Direction to settle (exploration):**
- Kill the child with the parent: put each Job child in a Windows Job Object
  with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, or have the child watch the
  parent pid and exit when it disappears.
- And/or make the child's final write conditional: it commits its result only
  while the Job row is still RUNNING and owned by its run, so a recovered Job
  cannot be overwritten.
- And/or startup recovery kills a still-alive child it finds for a RUNNING
  Job before marking it failed.

**Acceptance:**
- Hard-killing the app mid-Job leaves no Job child alive within a few seconds
  (Windows), and VRAM returns to the idle baseline before the restarted app
  starts the next PENDING Job.
- A recovered (FAILED) Job is never moved to COMPLETED by a late child.
- A test for whichever mechanism is chosen; the machine check above re-run and
  recorded in `plans/LOCAL-VERIFICATION.md`.

**Status:** needs-exploration
