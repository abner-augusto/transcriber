# Plan 046: A Source Reference to the original recording, so reruns can read it back

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report; do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**: confirm plan 045 is DONE in `plans/README.md`,
> then run
> `git diff --stat 5190429..HEAD -- api/meetings.py tasks/process_meeting.py tasks/reprocess_task.py services/audio_service.py services/audio_retention.py models/meeting.py migrations/runner.py preferences.py transcriber_cli/`.
> Any output is a STOP condition until compared with the excerpts below.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: MEDIUM (it reads files outside the app and adds a column and a setting)
- **Depends on**: 045
- **Category**: feature
- **Planned at**: commit `5190429`, 2026-10-14
- **Source**: the user, 2026-10-14, after plan 045: the app keeps no original
  recording, so it keeps a reference to where the original lives and reads it
  back when a rerun needs it. The triage workflow moves the audio from the
  inbox folder to the project folder minutes after upload, so re-pointing a
  stale path is the common case, not the exception.

## Why this matters

Plan 045 made a processed dual-track Meeting impossible to Re-diarize, fully
reprocess or duplicate, because it needs the mic and system tracks and the app
no longer holds them. The tracks still exist, in the meeting's project folder.
The app needs to know which file they are, to find them when they move, and to
refuse politely when they are gone.

## Decisions

1. **A Source Reference is stored per Meeting, per track, in one JSON column**
   `meetings.source_refs` (migration 6). Shape:

   ```json
   {"mic": {"path": "D:/proj/mic.wav", "name": "mic.wav", "size": 1503238144, "hash": "ab12..."},
    "system": {"path": null, "name": "system.wav", "size": 1503238200, "hash": "cd34..."}}
   ```

   - Keys: `audio` for a single-track Meeting and for a dual-track Meeting made
     from one stereo or multi-stream file (one file serves both tracks, as
     `mic_audio_filepath == system_audio_filepath` already says); `mic` and
     `system` for a dual-track Meeting made from two files.
   - `path` is absolute, or null when the client only knew the file name (a
     browser upload).
   - The identity (`name`, `size`, `hash`) is computed by the server from the
     bytes it saved at upload, before any Job runs, so it is never taken on
     trust from the client.

2. **The fast hash is SHA-256 over the file's size, its first 4 MiB and its
   last 4 MiB** (a file up to 8 MiB is hashed whole). Hashing a 1.5 GB WAV in
   full costs seconds, and would run at upload, at every re-point, at every
   check before a Job and at every search candidate. The head holds the
   container header, the tail changes under any truncation or re-encode, and
   the size is mixed in. Two different recordings agree on all of that only if
   they are the same length and share their first and last 4 MiB, which a
   microphone does not do. It will not notice an edit in the middle that keeps
   the size, which is the price of speed; the user's originals are not edited
   in place. The cheap check (state shown on the page, `reprocessable`) only
   stats the file and compares size, because `list_meetings` calls `to_dict`
   for every row; the hash is verified at re-point and before a Job starts.

3. **Capture.**
   - `transcriber_cli upload` sends the absolute path of each file as the
     form fields `source_path` and `system_source_path`. The server stores
     them verbatim after checking that they are absolute.
   - A browser upload sends none: it stores name, size and hash, with
     `path: null`. The browser exposes only the file name, never its location.
   - Meetings that exist today have **no reference and keep none**. The
     migration adds the column as NULL and guesses nothing. Document this.

4. **Re-pointing.** `PUT /api/meetings/{id}/sources`, body
   `{"source": PATH, "system_source": PATH?, "adopt": false}`;
   CLI `transcriber_cli set M --source PATH [--system-source PATH] [--adopt]`.
   - `source` is the `audio` or the `mic` file, `system_source` the `system`
     one, following the roles the Meeting's reference already has.
   - Both must be absolute paths of existing files. A file whose size or hash
     differs from the stored reference is refused with 409 "is not the same
     recording as ...". Nothing is changed on a refusal.
   - A Meeting with no reference has nothing to compare with. It is refused
     with a message naming `--adopt`. With `adopt`, the server accepts the file
     as that Meeting's recording only when its duration is within
     `max(2 s, 1%)` of the Meeting's, then stores its fingerprint. This is the
     one case that is not validated by hash, so the user must ask for it.
   - The triage workflow calls `set M --source NEWPATH` right after it moves
     the audio. The operator skill says so.
   - The page offers the same through a path text field in a Sources section,
     because the File API gives a browser the name of a chosen file, never its
     absolute path; the server runs on the same machine and can read what is
     typed.

5. **Resolution** (`services/source_reference.py`), used by every operation
   that needs the originals:
   1. Tracks the app still holds (legacy Meetings whose `mic_audio_filepath`
      and `system_audio_filepath` exist) win; no reference is needed.
   2. Otherwise each reference's stored `path` is used when the file exists
      and the fingerprint matches.
   3. Otherwise each folder in the new Preference `source_roots` (default
      empty) is walked for a file with the same size, then the same hash; the
      found path is written back to the reference so the next check is cheap.
      Names are not compared: the user may rename.
   4. Otherwise the operation fails: 400 when the Meeting has no reference at
      all, 409 when it has one that cannot be found, with the Meeting's id and
      the command `transcriber_cli set ID --source PATH`.

6. **Operations read the original in place.**
   - Full reprocess: the route stores the located originals in the path
     columns and `extract_dual_audio` reads them as ffmpeg inputs. Nothing is
     copied; ffmpeg writes only into the Meeting folder, and
     `drop_raw_audio` (plan 045) deletes only files inside that folder, so the
     user's original is never moved, modified or deleted. The task resolves
     again if the columns are empty.
   - Re-diarize, dual-track: when the processed tracks are gone, the task
     regenerates them from the located originals (`extract_dual_tracks`, new,
     which `extract_dual_audio` now also uses), diarizes, and deletes the tracks
     it made. Tracks it did not make (a legacy Meeting) stay.
   - Duplicate: tracks the app holds are hard-linked as in 045; otherwise the
     copy points its path columns at the located originals (no bytes copied),
     and always gets a copy of the reference.
   - `reprocessable` in `to_dict` is true for a single-track Meeting, a
     dual-track one that holds its tracks, and a dual-track one whose
     references all point at existing files of the stored size. It never
     hashes and never searches.

7. **UI.** The Meeting page gets a Sources section: each track with its name,
   size, saved path, state (`present`, `missing`, `not saved`) and a path field
   with a Re-point button that shows the server's refusal. Reprocess actions
   stay disabled only when the Meeting has neither held tracks nor a reference;
   when a reference is stale, they run, search, and show the 409 text.

8. **Setting.** `source_roots: list[str]` in Preferences, default `[]`,
   accepted by `PUT /api/settings/preferences` (absolute paths only; others are
   dropped). There is no Settings screen for it yet; it is a follow-up.

## Steps

Call the `tdd` skill first. Seams: the pure `services/source_reference.py`
functions; `POST /api/meetings` and the new `PUT /api/meetings/{id}/sources`
and the three operation routes through the FastAPI test client; the task
harness with `extract_dual_audio` and `extract_dual_tracks` replaced by
recorders; the CLI through the fake transport of `tests/test_transcriber_cli.py`;
the migration through the existing pattern. One test, one change, per slice.

1. **Migration 6 and column.** `meetings.source_refs` JSON, NULL; bump the
   migration counts in `tests/test_database_sqlite.py` to 6.
2. **Fingerprint and matching.**
3. **Capture at upload** (browser: path null; CLI fields: path stored; relative
   path refused; stereo file stored as `audio`).
4. **Re-point** (route + CLI): match, mismatch, adopt, missing file, relative
   path.
5. **Resolution, `reprocessable`, `source_roots`** and the routes' errors.
6. **Tasks**: process reads originals in place; Re-diarize regenerates and
   cleans its tracks; Duplicate references.
7. **Frontend**: Sources section, blocked reason.
8. **Docs.** ADR-0012, GLOSSARY (Source Reference), README, operator skill,
   plan 045 and its ADR where they now say "cannot".
9. **Gates.** `uv run --extra dev pytest -q`; `npm test` in `frontend/`. Mark
   046 DONE in `plans/README.md`.

## Hard boundaries

- Never move, modify or delete a user's original; every read is read-only.
- Never run the migration, the app, the CLI or a search against the real
  `storage/` or database. Tests use `tmp_path`.
- Out of scope: a Settings screen for `source_roots`, backfilling references
  for existing Meetings, per-Meeting disk usage.

## STOP conditions

- The drift check prints changes.
- A step needs to write inside a user's original folder.

## Done criteria

- `uv run --extra dev pytest -q`: all pass.
- `cd frontend && npm test`: all pass.

## Maintenance note

A new operation that needs the originals must go through
`services.source_reference.locate_tracks`, not read the path columns, or it
will break for a Meeting that was moved.
