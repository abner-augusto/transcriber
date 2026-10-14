# 01 - Retention and Compression for Stored Recordings

**Source:** disk cleanup on 2026-10-13 (biblioteca-iar session). `storage/`
had grown to 33 GB across 56 Meetings and filled drive C:.

**What to build:** A storage policy for Meeting audio, so `storage/` stops
growing without bound. Candidates to decide in the design session:

- compress the sources once processing finishes (FLAC is lossless; Opus is
  much smaller and is enough for ASR at 16 kHz), or drop them after a
  retention period;
- drop `mic_processed.wav` / `system_processed.wav` once `audio.wav` and the
  transcript exist, or regenerate them on demand;
- stop duplicating the sources when a Meeting is copied to rerun with another
  preset (`api/meetings.py:310-323` uses `shutil.copyfile`); share or
  reference them instead;
- show per-Meeting disk usage, with a manual "free space" action.

**Why:** what fills the disk is uncompressed WAV kept forever. A dual-track
Meeting stores `mic_source.wav` and `system_source.wav` of ~1.5 GB each, plus
two ~250 MB processed tracks and the ~250 MB `audio.wav` mix; single-track
Meetings also keep `original.mov`/`.mp4`. One 3.6 GB Meeting folder held
3.1 GB of sources.

**Blocked by:** none.

**Status:** done for retention (plan 045, 2026-10-14). Follow-ups below stay `needs-exploration`.

**State left by the manual cleanup (2026-10-13):** in every Meeting older than
7 days, these were deleted: `mic_source.wav`, `system_source.wav`,
`mic_processed.wav`, `system_processed.wav`, `original.mov`, `original.mp4`
and `original.wav` (78 files, 27.9 GB). `audio.wav` and `audio.wav.json` were
kept, and the user has the originals saved elsewhere. Consequences to handle:

- `mic_audio_filepath`, `system_audio_filepath` and `audio_filepath` in the
  database still point to the deleted files;
- copying one of those Meetings to rerun with another preset now fails in
  `shutil.copyfile` with `FileNotFoundError`;
- reprocessing them from source is impossible until the originals are put
  back.

**Decided 2026-10-14 (plan 045):** the app keeps no original recording; the
originals live in each meeting's project folder. After processing it keeps
only `audio.wav`; `mic_audio_filepath`/`system_audio_filepath` become NULL;
Duplicate shares files by hard link; migration 5 fixes the rows left by the
manual cleanup. A processed dual-track Meeting can no longer be Re-diarized,
fully reprocessed or duplicated.

**Follow-ups (not done):**
- ~~record where the original lives~~ done in plan 046 (Source Reference);
- keep the processed tracks only for dual-track Meetings (about 115 MB per
  hour per track) if Re-diarize of those matters;
- per-Meeting disk usage and a manual "free space" action;
- compression of `audio.wav` (not needed once sources are dropped).

**Open questions from the original exploration (answered above):**
- Which reprocessing paths really need the sources (rerun with another preset,
  dual-track reprocessing), and can `audio.wav` serve any of them?
- Compress, expire, or both? Which retention period?
- How should the app show a Meeting whose sources are gone: hide the rerun
  action, or offer to reattach the original?
