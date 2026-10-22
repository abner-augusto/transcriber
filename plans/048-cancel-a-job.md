# Plan 048: Cancel a Job

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving to the next step. When done,
> update the status row for this plan in `plans/README.md`.

## Status

- **Priority**: P2
- **Effort**: L
- **Risk**: MEDIUM (a status value, a column, a kill of the Job's whole process tree, and
  when a Job writes its results)
- **Depends on**: 019 (local runner), 045 and 046 (what a Meeting folder keeps)
- **Category**: feature
- **Planned at**: commit `68dbb92`, 2026-10-22
- **Source**: `.scratch/architecture-review/issues/09-cancel-job.md` (`needs-exploration`
  since 2026-09-24). The design below was decided on 2026-10-22 from that ticket, ADR-0010,
  ADR-0011, ADR-0012 and the code.

## Why this matters

A transcription takes tens of minutes on the GPU and cannot be stopped from the app: the
user who picked the wrong Preset, or queued the wrong file, waits it out or kills the
server. The first attempt (`LocalJobRunner.cancel` in plan 019) was removed on 2026-09-25
because it raced the runner loop (the route killed the child while the loop was reading its
exit and failing the Job) and marked Job and Meeting FAILED. This plan answers the three
open questions of ticket 09 and puts the whole transition in one place.

## Decisions

1. **`JobStatus.CANCELLED` comes back**, terminal like COMPLETED and FAILED. The value now
   has a producer, so `tests/test_dead_live_surface.py` is changed on purpose: its allowed
   set gains `"cancelled"`, and its docstring stops naming CANCELLED as removed.
2. **Cancelling records an intention, nothing more.** `LocalJobRunner.cancel(job_id)` sets
   `jobs.cancel_requested_at` (migration 8, a nullable DATETIME; only on a PENDING or
   RUNNING Job, and only the first time) and wakes the loop. It never touches the process
   and never changes a status. The loop of the runner, and only it, stops the child
   (`_stop_process`: terminate, then kill) and calls `jobs.finish_cancel`, which makes the
   transition. One writer of the end state is what removes the race of the first attempt.
3. **What the loop does with the intention**, checked about every 0.5 s through
   `jobs.cancel_requests()` (the unfinished Jobs with a request, and their status):
   - the active Job has it: stop the child, join it, drain its messages, then
     `jobs.finish_cancel`;
   - a queued PENDING Job has it (also while another Job is running): `jobs.finish_cancel`
     with no process. The active Job is never swept, because its child may be flipping it to
     RUNNING at that moment;
   - the intention arrives between picking a Job and starting its child: checked once more
     before the spawn.
4. **Too late once the final transaction is committed.** `jobs.finish_cancel` changes nothing
   when the Job is no longer PENDING or RUNNING and returns False: a Job whose final
   transaction committed first stays COMPLETED, its Meeting COMPLETED, and the intention is
   ignored. There is no window in which a Job becomes CANCELLED with the new results saved,
   because a task body commits nothing at the end: `running()` saves the results, the
   Meeting's COMPLETED and the Job's COMPLETED in one commit (`meeting_store`'s rebuild only
   flushes). Clean-up of files (dropping the originals, moving the dual-track mix over
   `audio.wav`) runs after that commit as `RunningJob.after_commit` actions; a kill between
   leaves stray files and a correct database. Tests kill the child (a `BaseException`)
   between the rebuild and the commit (nothing changed, the Job still RUNNING) and between
   the commit and the actions (COMPLETED, with the new results).
5. **Where the Meeting goes back to: the state the Job recorded.** `jobs.enqueue` writes the
   Meeting's status and `audio_filepath` on the Job (`previous_meeting_status`,
   `previous_audio_filepath`, migration 8). A cancel (PENDING or RUNNING, any Job kind)
   restores:
   - recorded COMPLETED: COMPLETED, nothing else touched. A silent Meeting with no Words, or
     one whose transcript the user emptied, is COMPLETED too: the old rule that looked for
     Words and Segments sent such a Meeting to UPLOADED and deleted data;
   - recorded UPLOADED: UPLOADED, `audio_filepath` back to the upload, and (RUNNING only) the
     partial Segments, Speakers, Words and Turns discarded;
   - recorded FAILED (a retry): FAILED, `audio_filepath` back, rows left as they are (the
     retry's own saved stages are what any failure would have left).
   Fallback only for a Job made before this plan (`previous_meeting_status` NULL, a Job
   queued across the upgrade): COMPLETED when the Meeting holds Words and at least one
   Segment, else UPLOADED and the partial discarded; `audio_filepath` untouched.
6. **What cancelling a RUNNING Job deletes**, before the Job is marked CANCELLED, as the end
   of a Job does (ADR-0011/0012), and never the original recording:
   - always: `mic_processed.wav`, `system_processed.wav`, and the half-written
     `audio.part.wav` (decision 8);
   - when the Meeting is not going back to COMPLETED: `audio.wav` (unless the Meeting's
     restored `audio_filepath` names it);
   - never: `original.*`, `mic_source.*`, `system_source.*` (the upload the app still holds
     for an UPLOADED Meeting, and what a legacy COMPLETED Meeting reruns from), anything
     outside the Meeting's own folder, and the originals a Source Reference points at.
   A PENDING Job started nothing and deletes nothing. A COMPLETED dual-track Meeting keeps
   the `mic_audio_filepath`/`system_audio_filepath` that `POST /process` pointed at the
   originals (the app only reads them); the next successful Job clears them.
7. **A Reprocessing writes nothing until its one final transaction; a first transcription
   saves each stage.** `RunningJob.reprocessing` is true when the recorded state is COMPLETED.
   Found while checking `tasks/process_meeting.py`: Full reprocess used to commit
   `audio_filepath`, `raw_transcription` (right after the Transcriber) and `raw_diarization`
   (right after the Diarizer) many minutes before the Segments were replaced, and
   `rebuild_speakers_and_segments` committed after deleting the old Segments and before
   writing the new ones; Re-diarize committed `raw_diarization` the same way. Killing the
   child in between would have left a COMPLETED Meeting whose Words or Turns no longer match
   its Segments, or none. Now:
   - a Reprocessing keeps the Words, Turns, audio path and duration in locals and assigns
     them just before the rebuild; the rebuild and `RunningJob`'s final commit are one
     transaction (the write lock is held only for the rebuild, not during the minutes of
     Transcriber or Diarizer work). Re-diarize, Re-identify and Reapply vocabulary are
     always transactional;
   - a first transcription (recorded UPLOADED or FAILED) goes on saving `audio_filepath` and
     `duration`, `raw_transcription` and `raw_diarization` as each stage finishes, as it
     always did, so a Job that fails late still allows Re-diarize, Re-identify and Reapply
     vocabulary. Cancelling it discards them (decision 5). Its Segments and Speakers still
     arrive only with the final transaction.
8. **The dual-track mix of a Reprocessing stays in `audio.part.wav` until the commit.**
   `extract_dual_audio(..., defer_mix=True)` writes the mix to `audio.part.wav`, returns
   that path to read in the meantime, and the `after_commit` action calls
   `AudioService.install_mix` (`os.replace` over `audio.wav`). A failure or a kill before the
   commit leaves the Meeting's `audio.wav` as it was, and the cancel deletes the `.part`. A
   first transcription (nothing to protect) installs the mix at once. A single-track rerun
   reads `audio.wav` in place and writes nothing.
9. **The whole process tree stops.** The Job child starts the Engine runtime (a Python
   subprocess on the GPU), `whisper.cpp`/`parakeet.cpp` and ffmpeg. Terminating only the
   child leaves them running and holding the GPU while the next Job starts. `_stop_process`
   now ends the tree: `taskkill /T /F` on Windows (a failure is logged with its exit code and
   output); on POSIX the child becomes the leader of its own session (`os.setsid`) and the
   group gets SIGTERM, then SIGKILL if the child is still alive after 5 s, always sent
   before the child is reaped so that the group id cannot belong to another process. Limits
   accepted: `/T` finds descendants through their parent, so if the child already died its
   descendants are not found; on Windows `hard` changes nothing (`/F` is already forced);
   on POSIX a descendant that ignores SIGTERM after the child exited on its own is left.
   `os.setsid` also means Ctrl-C in the server's terminal no longer reaches the child (the
   server's shutdown stops it) and a hard kill of the server leaves the tree orphaned, as
   before. This also fixes the same orphans after a timeout or a shutdown. `psutil` is not
   added.
10. **Surface** (ADR-0010: the CLI reaches whatever the page does):
    - `POST /api/meetings/{id}/cancel` -> the Job with `cancel_requested_at` set (200). It
      is asynchronous: the response says the request was recorded, and the Job is still
      `running` for a moment. 404 for a missing Meeting; 409 when the Meeting has no
      PENDING or RUNNING Job. Asking twice returns the same Job.
    - the runner publishes `{"type": "cancelled"}` when the transition is done; the page
      refetches on it.
    - `transcriber_cli cancel <Meeting>` posts and returns once the request is recorded;
      with `--wait` (as `process` and `reprocess`) it waits (`--timeout`, default 60 s; exit
      3 on timeout) until the Job leaves PENDING/RUNNING and prints where the Meeting went
      back to (exit 1 if the Job ended some other way first). `_wait` (`process --wait`,
      `wait`) learns the `cancelled` status; today it would poll forever.
    - the Meeting page shows Cancel beside the progress while a Job runs, disabled with
      "Cancelling..." once the request is made.

## Steps

1. **Status, columns, migration**: `JobStatus.CANCELLED`; `Job.cancel_requested_at`,
   `previous_meeting_status`, `previous_audio_filepath` (`to_dict` reports the first);
   migration 8 adds the three with the strict `_add_column` (a database without `jobs` is not
   a production case: the old test fixtures got a `jobs` table); `fail()` leaves a
   CANCELLED Job alone; update `tests/test_dead_live_surface.py`.
2. **Results in one transaction** (decisions 4, 7, 8): tests first for the tasks (`tests/
   test_cancel_safe_tasks.py`: a `BaseException` raised at the Diarizer, the speaker
   naming, the Segment write, right after the rebuild or after the final commit, which
   `running()` does not catch and so behaves like a killed child), then
   `RunningJob.reprocessing`/`after_commit`, `process_meeting.py`, `reprocess_task.py`,
   `meeting_store.py` (the rebuild only flushes) and `AudioService.extract_dual_audio`
   (`audio.part.wav`, `defer_mix`, `install_mix`); `audio_retention` splits into
   `forget_raw_audio` (in the transaction) and `delete_raw_audio` (after it).
3. **Intention and transition** (`jobs/__init__.py`): `cancel(db, meeting_id)` (the route's
   front door), `request_cancel(job_id)`, `cancel_requests()` and `finish_cancel(job_id)`
   with its restore rule (decisions 4, 5, 6); `JobRunner` gains `cancel(job_id)`;
   `InlineJobRunner.cancel` records the intention too. `meeting_store.discard_transcript`
   clears a transcript; `services/audio_retention.drop_cancelled_work` deletes the files.
4. **Runner** (`jobs/runners.py`): `LocalJobRunner.cancel`, the loop checks (decision 3),
   `_stop_process` ends the tree (decision 9). Tests with real spawned children, in
   `tests/test_cancel_job.py`: PENDING -> CANCELLED with no process; RUNNING -> CANCELLED
   on a first transcription (Meeting UPLOADED, partial rows and work files gone, original
   kept) and on a Reprocessing (Meeting COMPLETED, Segments and Words as before); a cancel
   next to the natural end (COMPLETED wins; no half state); a grandchild process is dead
   afterwards.
5. **API and CLI**: the route and its tests in `tests/test_meeting_api.py`; `cancel` in
   `transcriber_cli/main.py` and `_wait`.
6. **Frontend**: `cancelMeeting` in `api.ts`; `"cancelled"` in `Job.status`,
   `ProgressUpdate.type` and `meetingSocketAction` (test in `meetingSocket.test.ts`); the
   button in `MeetingPage.tsx`.
7. **Docs**: README route table and Job lifecycle, GLOSSARY (Job, Cancel), operator
   SKILL.md, the comment in `models/meeting.py`/`jobs`, ticket 09 done, this plan's row.

## Verify

| What | Command | Expected |
| --- | --- | --- |
| Backend | `pytest` from the repo root | all pass |
| Frontend | `npm test` in `frontend/` | all pass |
| By hand | the checklist in the report of the executor (Cancel on the page, on a real Preset) | Meeting back to UPLOADED/COMPLETED, no `python`/`ffmpeg` left running, GPU memory freed |

## STOP conditions

- The swap-at-the-end in decision 7 breaks `tests/test_reprocess_keeps_edits.py` or
  `tests/test_speaker_carry.py` in a way that needs a change to what they assert: stop and
  report, because the edit-preservation contract (plan 028) is not this plan's to change.
- The tree kill needs a dependency, or `taskkill` is absent on the target machine.

## Outcome (2026-10-22)

Done, revised after code review the same day (decisions 4, 5, 7, 8 and 9 above are the
revised text). Notes the next reader needs:

- The late-cancel race is covered at three levels: `finish_cancel` is a no-op on a finished
  Job (unit); a runner whose loop read the request before the child completed leaves the Job
  COMPLETED (real child, `tests/test_cancel_job.py`); and killing the task after the rebuild
  but before the final commit changes nothing, while killing it after the commit leaves the
  new results with the Job COMPLETED (`tests/test_cancel_safe_tasks.py`). The runner's own
  check ignores a Job that is no longer PENDING or RUNNING.
- Not verified here: a real cancel on a real Preset and GPU, and the POSIX branch of the
  process-tree kill (`os.setsid` + `killpg`); the Windows branch (`taskkill /T /F`) is
  tested with a real grandchild process.
- Jobs queued across the upgrade (no recorded state) use the fallback of decision 5.
- `RunningJob` has a fourth field (`after_commit_actions`), so it no longer unpacks as
  `(db, meeting, job)`.

## Out of scope

- Cancelling from a socket message, or a "Cancel all": one Job at a time, from the Meeting.
- Resuming a cancelled Job. The Meeting is back where it was; the user starts it again.
- Cancelling a Job from another Meeting's page.
