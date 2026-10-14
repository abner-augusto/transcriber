# The app references the originals it does not keep

**Status**: accepted (2026-10-14, plan 046). Amends ADR-0011.

ADR-0011 stopped the app from keeping the original recordings. A processed
dual-track Meeting then lost Re-diarize, Full reprocess and Duplicate, because
they need the separate mic and system recordings. The originals still exist in
the meeting's project folder, so the app keeps a **Source Reference** to each:
its absolute path (when known), file name, size and a fast hash. A rerun reads
the original from there.

## Decisions

- The reference is stored per Meeting and track in `meetings.source_refs`. The
  server computes name, size and hash from the bytes it received at upload.
  `transcriber_cli upload` also sends the absolute path; a browser cannot, so
  its reference has no path until the user adds one.
- The hash is SHA-256 over the size, the first 4 MiB and the last 4 MiB. It is
  fast on a 1.5 GB WAV and detects a different recording, a truncation and a
  re-encode. It does not detect an edit in the middle that keeps the size.
- A path goes stale minutes after upload, when the user's triage moves the file
  from the inbox to the project folder. `set M --source NEWPATH` (CLI) or the
  Original recording section (page) re-points it, and the file must match the
  stored size and hash. A Meeting uploaded before references existed has none
  and is not backfilled; `--adopt` attaches a file to it on the user's word,
  checked only by duration.
- When a rerun needs the originals: the stored path if it still matches, else a
  search of the folders in the `source_roots` Preference (empty by default) for
  a file with the same size and hash, else a 409 that names the command to
  re-point.
- The app only reads an original. It never moves, modifies or deletes it. The
  working files a Job makes live in the Meeting's folder and are dropped again
  (ADR-0011).

## Consequences

- `reprocessable` is true for a dual-track Meeting whose originals are where
  the reference says. It only stats files; it never hashes or searches.
- Re-diarize of a dual-track Meeting makes the processed tracks again from the
  originals and deletes them when the Job ends.
- Duplicate points the copy at the originals instead of copying them.
- A user's own workflow that moves recordings must call `set M --source` after
  each move, or rely on `source_roots`.
