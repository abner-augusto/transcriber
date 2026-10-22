# 09 - Cancel a Running Job

**Source:** design session on tickets 02/04/05, 2026-09-24.

**What to build:** A Cancel button on the Meeting page while a Job runs. The
route calls the local runner's `cancel(job_id)` (plan 019), which kills the
child process; the Job ends as CANCELLED and the Meeting returns to its
previous usable state (UPLOADED if never transcribed, COMPLETED if this was a
Reprocessing of a completed Meeting).

**Blocked by:** plan 019.

**Status:** ready-for-agent (design in `plans/048-cancel-a-job.md`, 2026-10-22)

**Note (2026-09-25):** the speculative `LocalJobRunner.cancel` that plan 019
added was removed during review: nothing called it, it raced the runner loop,
and it marked Job and Meeting FAILED rather than the CANCELLED/restored states
this ticket wants. The design session should define the runner hook together
with the route.

**Open questions:**
- `JobStatus.CANCELLED` was removed as dead code (`tests/test_dead_live_surface.py`);
  restoring it needs that test updated deliberately.
- What does the Meeting show after cancelling a first transcription halfway?
- Cancel a PENDING Job too (just remove it from the queue)?

## Design session, 2026-10-22

**Status now:** ready-for-agent. Executable plan: `plans/048-cancel-a-job.md`.

Answers to the open questions:

- **`JobStatus.CANCELLED`** returns, as a terminal state with a producer.
  `tests/test_dead_live_surface.py` is updated on purpose.
- **A first transcription cancelled halfway** puts the Meeting back to UPLOADED: the
  partial Segments, Speakers and Words are discarded and the Job's work files
  (`audio.wav`, processed tracks) are deleted as the normal end of a Job does
  (ADR-0011/0012). The original is never touched. **A Reprocessing cancelled**
  puts the Meeting back to COMPLETED with the previous transcript intact.
- **A PENDING Job** is cancelled too: it leaves the queue as CANCELLED, with no process.

Mechanics (the cause of the 2026-09-25 revert was a second writer of the end state):
`LocalJobRunner.cancel(job_id)` only records `jobs.cancel_requested_at`; the loop of the
runner stops the child and makes the transition. Finding: Full reprocess and Re-diarize
wrote the new Words and Turns many minutes before replacing the Segments, so the plan also
makes them write their results only at the end. Surface: `POST /api/meetings/{id}/cancel`,
`transcriber_cli cancel <Meeting>` (ADR-0010) and a Cancel button on the Meeting page.
