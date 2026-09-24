# 09 - Cancel a Running Job

**Source:** design session on tickets 02/04/05, 2026-09-24.

**What to build:** A Cancel button on the Meeting page while a Job runs. The
route calls the local runner's `cancel(job_id)` (plan 019), which kills the
child process; the Job ends as CANCELLED and the Meeting returns to its
previous usable state (UPLOADED if never transcribed, COMPLETED if this was a
Reprocessing of a completed Meeting).

**Blocked by:** plan 019.

**Status:** needs-exploration

**Open questions:**
- `JobStatus.CANCELLED` was removed as dead code (`tests/test_dead_live_surface.py`);
  restoring it needs that test updated deliberately.
- What does the Meeting show after cancelling a first transcription halfway?
- Cancel a PENDING Job too (just remove it from the queue)?
