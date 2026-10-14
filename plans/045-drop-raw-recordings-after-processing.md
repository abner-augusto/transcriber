# Plan 045: The app keeps only the derived `audio.wav` once a Meeting is processed

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report; do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**: run
> `git diff --stat c4054ed..HEAD -- api/meetings.py tasks/process_meeting.py tasks/reprocess_task.py tasks/diarization.py services/audio_service.py models/meeting.py migrations/runner.py main.py`.
> Any output is a STOP condition until compared with the excerpts below.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MEDIUM (it deletes files after a Job, and adds a data migration)
- **Depends on**: none
- **Category**: design + bug
- **Planned at**: commit `c4054ed`, 2026-10-14
- **Source**: `.scratch/recording-storage-retention/issues/01-recording-storage-retention.md`
  (`storage/` reached 33 GB over 56 Meetings and filled drive C:). The user
  replaced the design session with one decision on 2026-10-14:
  - "the app must NOT keep the raw/original recording": the originals always
    live outside the app, in the project folder of each meeting.

## Why this matters

Uncompressed WAV kept forever fills the disk. A dual-track Meeting held two
~1.5 GB sources, two ~250 MB processed tracks and a ~250 MB `audio.wav`. The
manual cleanup of 2026-10-13 deleted the sources and processed tracks of every
Meeting older than 7 days, which left database rows pointing at deleted files
and a Duplicate action that crashes. This plan makes that state the designed
one.

## Decisions

1. **Kept after a Meeting finishes processing: `audio.wav` only** (and the
   `audio.wav.json` next to it, which this plan does not touch). Dropped:
   `original.*`, `mic_source.*`, `system_source.*`, `mic_processed.wav`,
   `system_processed.wav`. A Meeting that is not processed (`UPLOADED`,
   `FAILED`) keeps what it has, so a retry still works.

2. **Evidence for what `audio.wav` must serve** (16 kHz mono PCM, loudness
   normalized, the mix for a dual-track Meeting):

   | Feature | Reads | Works from `audio.wav` alone? |
   |---|---|---|
   | Playback (`main.py:stream_audio`) | `meeting.audio_filepath` | yes |
   | Speaker Voice Profile clips (`api/speaker_profiles.py`) | `meeting.audio_filepath` | yes |
   | Speaker naming in a Job (`SpeakerIdService.name_speakers`) | `audio_path` = `audio.wav` | yes |
   | Re-identify, Re-apply vocabulary | stored Words and Turns | yes (no audio) |
   | Re-diarize, single-track | `meeting.audio_filepath` | yes |
   | Full reprocess, single-track | `meeting.audio_filepath`; `extract_audio` skips ffmpeg when the input already is `audio.wav` | yes. It already did: `process_meeting_task` overwrites `audio_filepath` with `audio.wav` on its first run, so `original.*` was never read again after that |
   | Edits surviving reprocessing | stored in the database | yes |
   | Re-diarize, dual-track | `tasks/diarization._diarize_dual_track`: VAD on `mic_processed.wav` for the host, the Diarizer on `system_processed.wav` for the remote Speakers | **no**: the mix cannot separate the host from the remote |
   | Full reprocess, dual-track | `extract_dual_audio(mic, system)` | **no** |
   | Duplicate & reprocess, dual-track | the two sources | **no** |

   So the dual-track Meeting loses three actions once processed. Keeping the
   processed tracks would bring back Re-diarize (2 x ~115 MB per hour), but the
   decision is to keep one file. The user's manual cleanup already deleted the
   tracks of every old Meeting. Open question for the user, stated in the
   report: keep the processed tracks (or FLAC copies of them) only for
   dual-track Meetings?

   Compression of `audio.wav` (FLAC/Opus) is not done: `audio.wav` is the
   input of every Engine and of the player, `stream_audio` serves it as
   `audio/wav`, and at 16 kHz mono it is ~115 MB per hour, which the rest of
   this plan stops multiplying by five.

3. **Database paths follow what is kept.**
   - `audio_filepath` always points at `audio.wav` once processed (it already
     did).
   - `mic_audio_filepath` and `system_audio_filepath` become NULL when the
     sources are dropped. `is_dual_track` stays true: it describes how the
     Meeting was diarized.
   - A dual-track Meeting with NULL source paths cannot be re-run from audio.
     `Meeting.to_dict()` gets `reprocessable`: true for a single-track Meeting,
     and for a dual-track one only while both source paths are set. The Meeting
     page disables Re-diarize, Full reprocess and Duplicate & reprocess when it
     is false and says why.

4. **Routes fail early with a clear message, not with `FileNotFoundError`.**
   For a dual-track Meeting that is not `reprocessable`, `POST /process`,
   `POST /rediarize` and `POST /duplicate` answer 400:
   "This dual-track Meeting no longer has its mic and system tracks (the app
   keeps only the mixed audio after processing), so it cannot be ...". A
   Meeting whose audio file is missing on disk answers 400 for `duplicate`.

5. **Duplicate & reprocess shares instead of copying.** The copy gets a hard
   link to each source (`os.link`), so no bytes are duplicated and deleting
   either Meeting leaves the other intact. Where a link is impossible (another
   volume, a filesystem without links) it falls back to `shutil.copyfile`. The
   copy is then processed like any Meeting, and its own retention step drops
   its links. A single-track Meeting duplicates its `audio.wav` the same way.
   The checks run before the copy Meeting row exists, so a refusal leaves
   nothing behind.

6. **Existing Meetings in the broken state get migration 5**, "audio paths of
   deleted files". For each Meeting:
   - `mic_audio_filepath` / `system_audio_filepath` whose file does not exist
     become NULL;
   - an `audio_filepath` whose file does not exist is repointed to
     `audio.wav` in the same folder when that exists, else becomes NULL;
   - a path is judged only when its folder exists: a missing folder (storage
     unmounted, another working directory) means "cannot tell", and the row is
     left alone.

   It changes database rows only, never files, and is idempotent. **It is
   written and tested here but not run against the real database**; it runs by
   itself the next time the app starts after this branch is merged (see
   `database.init_db`). The report says so to the user.

7. **Not in this plan** (follow-ups, written into the issue): recording where
   the original lives (a `source_path` the CLI `upload` sends, so a reprocess
   or a dual-track Re-diarize could read it back); per-Meeting disk usage and
   a manual "free space" action; compressing or expiring anything else.

## Steps

Call the `tdd` skill first. The seams, as in plans 028 to 044, are the task
harness (`tests/task_harness.py`), the FastAPI test client, and the migration
test pattern in `tests/test_database_sqlite.py`; plus the pure function
`drop_raw_audio`.

1. **Retention step.** New `services/audio_retention.py` with
   `drop_raw_audio(meeting)`: deletes the dropped names from the Meeting's
   folder, never `audio.wav` nor the file `meeting.audio_filepath` names, never
   anything outside the folder, tolerates missing files and a file that cannot
   be deleted (logs a warning), then sets `mic_audio_filepath` and
   `system_audio_filepath` to None. Test it directly with a folder of files.
2. **Run it after success.** `tasks/process_meeting.py` calls it as the last
   step of `process_meeting_task`, then commits. Harness tests: after a
   single-track and a dual-track Job the folder holds only `audio.wav`; after
   a Job that fails, the sources are still there.
   `tests/test_reprocess_dual_track.py` writes the processed tracks again after
   processing, because the tasks still work for a Meeting that has them.
3. **`reprocessable` and the routes.** `Meeting.reprocessable` and its entry
   in `to_dict`; the 400 refusals in `start_processing`, `rediarize_meeting`
   and `duplicate_meeting`; the sharing copy in `duplicate_meeting`. API
   tests: each refusal creates no Job and no Meeting; a duplicate with sources
   present shares them (`os.path.samefile`) and queues one Job; a single-track
   duplicate whose file is gone answers 400.
4. **Migration 5** in `migrations/runner.py` and its tests (dual-track row
   with deleted sources, single-track row repointed, row with a missing folder
   untouched, idempotent). Update the expected migration count to 5 in
   `tests/test_database_sqlite.py`.
5. **Frontend.** `reprocessable` in `types.ts`; the three Reprocess menu
   items are disabled with an explanation when it is false.
6. **Docs.** `GLOSSARY.md` (Meeting), `README.md` (what is stored), the
   operator skill (`Re-diarize` of a dual-track Meeting), ADR-0011, the issue
   status, and a "Follow-ups" section in the issue.
7. **Gates.** `uv run --extra dev pytest -q` from the root and `npm test` in
   `frontend/`. Both pass. Mark 045 DONE in `plans/README.md`.

## Hard boundaries

- Never run the migration, the app, the CLI or the retention step against the
  real `storage/` or database. Tests use `tmp_path`.
- Out of scope: compression, expiry, disk-usage display, the `source_path`
  field.

## STOP conditions

- The drift check prints changes.
- A test shows a feature in the table above reading a dropped file.

## Done criteria

- `uv run --extra dev pytest -q`: all pass.
- `cd frontend && npm test`: all pass.
- `rg -n "shutil.copyfile" api/meetings.py` appears only inside the link
  fallback.

## Outcome

Executed as written. Two additions found while implementing:
- Duplicate of a dual-track Meeting whose two paths are the same stereo file
  now keeps one shared file (`original.<ext>`) in the copy. Before, the copy
  held two separate files, so the pipeline's same-file check failed and each
  track was a downmix instead of a channel.
- The Meeting page disables the three Reprocess actions through
  `reprocessBlockedReason` (`frontend/src/utils/reprocess.ts`).

Migration 5 was not run against the real database; it runs by itself the next
time the app starts after this branch is merged.

## Maintenance note

Deleting files is the point of this plan, so the list of dropped names lives
in one place (`services/audio_retention.py`). A new artifact written to the
Meeting folder by `AudioService` must be added there or it will accumulate
again.
