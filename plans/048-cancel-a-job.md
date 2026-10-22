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
   (`_stop_process`: terminate, then kill) and calls `jobs.cancel_job`, which makes the
   transition. One writer of the end state is what removes the race of the first attempt.
3. **What the loop does with the intention**, checked about every 0.5 s:
   - the active Job has it: stop the child, join it, drain its messages, then
     `jobs.cancel_job`;
   - a queued PENDING Job has it (also while another Job is running): `jobs.cancel_job`
     with no process. The active Job is never swept, because its child may be flipping it to
     RUNNING at that moment;
   - the intention arrives between picking a Job and starting its child: checked once more
     before the spawn.
4. **The race at the natural end.** `jobs.cancel_job` changes nothing when the Job is no
   longer PENDING or RUNNING and returns False. A child that committed COMPLETED just before
   being stopped wins: the Job stays COMPLETED, the intention is ignored. SQLite commits are
   atomic, so the result is either all of the Job's work or none of it, never half.
5. **Where the Meeting goes back to.** COMPLETED when it still has a stored transcription
   (Words) and at least one Segment; otherwise UPLOADED (it is never transcribed, or it was
   left half by an older failed run). This holds for every Job kind (Full reprocess,
   Re-diarize, Re-identify, Reapply vocabulary) and for a PENDING Job. A Meeting with
   Segments the user has edited keeps them: they are in the rows the Job had not replaced.
6. **What cancelling a RUNNING Job deletes**, as the end of a Job does (ADR-0011/0012), and
   never the original recording:
   - always: `mic_processed.wav`, `system_processed.wav`, and the half-written
     `audio.part.wav` (decision 8);
   - when the Meeting goes back to UPLOADED only: `audio.wav` (unless the Meeting's
     `audio_filepath` names it), and any Segment, Speaker, `raw_transcription` and
     `raw_diarization` left by an earlier run;
   - never: `original.*`, `mic_source.*`, `system_source.*` (the upload the app still holds
     for an UPLOADED Meeting, and what a legacy COMPLETED Meeting reruns from), anything
     outside the Meeting's own folder, and the originals a Source Reference points at.
   A PENDING Job started nothing and deletes nothing.
7. **A Reprocessing must write its results only at the end.** Checked in
   `tasks/process_meeting.py` and `tasks/reprocess_task.py`: they did **not**. Full
   reprocess committed `meeting.audio_filepath`, `raw_transcription` (right after the
   Transcriber) and `raw_diarization` (right after the Diarizer) many minutes before the
   Segments were replaced, and `rebuild_speakers_and_segments` committed after deleting the
   old Segments and Speakers and before writing the new ones. Re-diarize committed
   `raw_diarization` the same way. Killing the child anywhere in between would have left a
   COMPLETED Meeting whose Words or Turns no longer match its Segments (or with no Segments
   at all). The change is small, so it is part of this plan:
   - the task bodies keep the Words and Turns in locals and assign `audio_filepath`,
     `raw_transcription` and `raw_diarization` right before the rebuild, so they commit
     with it;
   - `rebuild_speakers_and_segments` replaces the Segments and Speakers in one transaction
     (the `commit()` after the deletes becomes a `flush()`); the write lock is held only for
     the rebuild, not during the minutes of Transcriber or Diarizer work;
   - `meeting.duration` is still committed after the audio is extracted: it is a fact about
     the audio, and the runner reads it to lengthen the time limit of a long file.
   `drop_raw_audio` already ran after the results; it stays after them.
8. **A dual-track mix is written to `audio.part.wav` and moved over `audio.wav` when ffmpeg
   finishes** (`os.replace`). Without it, cancelling a Full reprocess of a dual-track Meeting
   during its first minute could cut `audio.wav` in half: the file of a COMPLETED Meeting,
   which the page plays. A single-track rerun reads `audio.wav` in place and writes nothing.
9. **The whole process tree stops.** The Job child starts the Engine runtime (a Python
   subprocess on the GPU), `whisper.cpp`/`parakeet.cpp` and ffmpeg. Terminating only the
   child leaves them running and holding the GPU while the next Job starts. `_stop_process`
   now ends the tree: `taskkill /T /F` on Windows; on POSIX the child becomes the leader of
   its own process group (`os.setsid`) and the group gets the signal. This also fixes the
   same orphans after a timeout or a shutdown. `psutil` is not added.
10. **Surface** (ADR-0010: the CLI reaches whatever the page does):
    - `POST /api/meetings/{id}/cancel` -> the Job with `cancel_requested_at` set (200). It
      is asynchronous: the response says the request was recorded, and the Job is still
      `running` for a moment. 404 for a missing Meeting; 409 when the Meeting has no
      PENDING or RUNNING Job. Asking twice returns the same Job.
    - the runner publishes `{"type": "cancelled"}` when the transition is done; the page
      refetches on it.
    - `transcriber_cli cancel <Meeting>` posts, then waits (up to 60 s) until the Job leaves
      PENDING/RUNNING and prints where the Meeting went back to. `--no-wait` returns at
      once. `_wait` (`process --wait`, `wait`) learns the `cancelled` status; today it would
      poll forever.
    - the Meeting page shows Cancel beside the progress while a Job runs, disabled with
      "Cancelling..." once the request is made.

## Steps

1. **Status, column, migration**: `JobStatus.CANCELLED`; `Job.cancel_requested_at`
   (`to_dict` reports it); migration 8 `_add_column("jobs", "cancel_requested_at",
   "DATETIME")`; `fail()` leaves a CANCELLED Job alone; update
   `tests/test_dead_live_surface.py`.
2. **Results at the end** (decisions 7, 8): tests first for the tasks (`tests/
   test_cancel_safe_tasks.py`: a stage raising `KeyboardInterrupt`-like stop after the
   Transcriber leaves the stored Words, Turns and Segments of a COMPLETED Meeting as they
   were), then the move in `process_meeting.py`, `reprocess_task.py`, `meeting_store.py`,
   `AudioService.extract_dual_audio`.
3. **Intention and transition** (`jobs/__init__.py`): `request_cancel(job_id, ...)`,
   `cancel_job(job_id, ...)` and `restore_after_cancel` (decisions 4, 5, 6); `JobRunner`
   gains `cancel(job_id)`; `InlineJobRunner.cancel` records the intention too.
   `services/audio_retention.drop_cancelled_work` deletes the files.
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

## Out of scope

- Cancelling from a socket message, or a "Cancel all": one Job at a time, from the Meeting.
- Resuming a cancelled Job. The Meeting is back where it was; the user starts it again.
- Cancelling a Job from another Meeting's page.
