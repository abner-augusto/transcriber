# 09 - Cancel a Running Job

**Source:** design session on tickets 02/04/05, 2026-09-24.

**What to build:** A Cancel button on the Meeting page while a Job runs. The
route calls the local runner's `cancel(job_id)` (plan 019), which kills the
child process; the Job ends as CANCELLED and the Meeting returns to its
previous usable state (UPLOADED if never transcribed, COMPLETED if this was a
Reprocessing of a completed Meeting).

**Blocked by:** plan 019.

**Status:** done (plan 048, 2026-10-22; the manual Cancel check on a real Preset is still the user's)

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

**Status now:** done. It was ready-for-agent after this session; executable plan: `plans/048-cancel-a-job.md`.

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

### Decisions after code review, 2026-10-22

- **The Meeting goes back to the state the Job recorded**, not to what its data suggests:
  `jobs.enqueue` stores the Meeting's status and audio path on the Job. COMPLETED stays
  COMPLETED untouched (so a Reprocessing of a silent Meeting, or of one whose transcript the
  user emptied, no longer turns UPLOADED and loses data); UPLOADED goes back to the upload and
  discards the partial; FAILED (a retry) goes back to FAILED. The Words-and-Segments rule
  remains only as the fallback for a Job queued before the upgrade.
- **Too late once the final transaction is committed.** A Reprocessing and a first
  transcription end in one commit with the results, the Meeting's COMPLETED and the Job's
  COMPLETED; if it landed first, the Job stays COMPLETED and the cancel is ignored. File
  clean-up runs after that commit.
- **Only a Reprocessing writes nothing until the end.** A first transcription saves each
  stage as it did, so a late failure still allows Re-diarize, Re-identify and Reapply
  vocabulary; its cancel discards those stages.
- The dual-track mix of a Reprocessing stays in `audio.part.wav` until that commit; the
  Reprocessing does not touch `duration` either.
- `transcriber_cli cancel` returns after the request and waits only with `--wait`, like
  `process` and `reprocess`.
