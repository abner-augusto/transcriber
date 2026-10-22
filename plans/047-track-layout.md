# Plan 047: Detect the tracks of a single file, and let the user overrule

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving to the next step. When done,
> update the status row for this plan in `plans/README.md`.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: MEDIUM (a column, and a change to which audio a dual-track Meeting reads)
- **Depends on**: 046
- **Category**: bug + feature
- **Planned at**: commit `4819961`, 2026-10-15
- **Source**: the user, 2026-10-15: a single OBS file carries the microphone and the
  desktop audio as separate tracks; the app should find them, ignore a fake stereo,
  handle more than two tracks, and let the user fix a wrong guess.

## Why this matters

`.scratch/dual-track-audio/issues/01` is marked done, but single-file detection never
worked. Checked against real ffmpeg/ffprobe on 2026-10-15:

- `AudioService.probe_audio` keeps a stream only when `stream.get("codec")` is set. ffprobe
  emits `codec_name` and `codec_type`, never `codec`, so the probe always reports 0 audio
  streams and 1 channel. A stereo or multi-track file is never detected; it is processed as
  one mixed mono track. The tests mock a schema ffprobe does not produce.
- `_split_dual` builds `pan=mono|c0=1:c1=0`; ffmpeg rejects it ("Option 'c1' not found").
  The documented forms (`pan=mono|c0=c0`, `pan=mono|c0=c1`) work.

- ffprobe prints UTF-8 (track titles such as "Áudio do computador", file names with
  accents) and `text=True` decoded it with the Windows code page (cp1252); byte 0x81
  crashed the reader thread and `stdout` came back `None`. Found on the user's real OBS
  recordings.

So the split is untested against ffmpeg and would fail if it were ever reached. Beyond
the fix, three gaps remain: a stereo file with identical channels is "dual-track";
only the first two tracks are used; and OBS track 1 is usually a mix of the others.

## Decisions

1. **A candidate track** is one stream of the file, or one channel of a multi-channel
   stream. `stream` is the ordinal among audio streams (`-map 0:a:N`), `channel` is `null`
   for a whole stream.
2. **Classification** (pure function over mono samples, no ffmpeg):
   - `silent`: RMS below a floor.
   - `duplicate`: correlation with an earlier candidate >= 0.98 (a fake stereo collapses
     to one).
   - `mix`: correlation with the sum of the *other* usable candidates >= 0.95 (OBS track 1).
   - otherwise `speech`.
3. **Layout**: among the `speech` candidates, the names the recorder gave the tracks decide
   which is the mic and which the system ("Microfone"/"Microphone"/"Mic" and
   "Computador"/"Desktop"/"System"); without a clear name the file's order does, the first
   being the mic. The user's OBS profile puts the desktop first (`a:0` "Computador",
   `a:1` "Microfone"), so order alone would swap them. Two or more speech candidates:
   dual-track. One: a single file read from that candidate. None: a single file as
   before (all candidates are silent or mixes). Each stream is one candidate, even a
   stereo one (mixed down); channels are candidates only for a file with a single stream.
4. **Sampling**: analysis decodes short windows (~60 s at 10%, 50%, 90% of the duration,
   8 kHz mono), so its cost does not grow with the file (about 1 s for a 7 and a 13
   minute recording). A track the windows find silent is confirmed against the loudest
   sample of the whole file (`volumedetect`, above -50 dBFS is not silent): the user's
   desktop track is nearly silent until something plays, and a burst between windows
   must not be lost.
5. **Persistence**: one JSON column `meetings.track_layout` (migration 7), nullable:
   `{"tracks": [{"stream", "channel", "status", "level_db", "title"}], "mic": sel|null,
   "system": sel|null, "manual": bool}`. Extraction reads the assignment; it never
   re-probes. `duplicate_meeting` copies it.
6. **Override**: `PUT /api/meetings/{id}/tracks` with `{"mic": sel|null, "system": sel|null}`,
   only while the Meeting is `uploaded` (409 otherwise). `system: null` makes it a single
   file. The selector UI sits on the uploaded Meeting page; the CLI gets
   `set --mic-track/--system-track`.

## Steps

1. **Probe fix** (`services/audio_service.py`): filter on `codec_type == "audio"`; keep
   `tags.title` per stream. Fixtures are real ffprobe output.
2. **Classifier** (`services/track_analysis.py`): `classify(samples) -> list[status]`.
3. **Analysis** (`AudioService.analyze_tracks(path) -> track_layout`): decode windows,
   classify, assign.
4. **Extraction by layout**: `_split_dual` / `extract_dual_*` take the layout instead of
   probing and hard-coding 0 and 1; the pan filters use the documented syntax. A single
   file with a chosen candidate extracts that candidate.
5. **API**: `create_meeting` stores the layout (analysis in a thread pool);
   `PUT /tracks`; `duplicate` copies it; `tasks/process_meeting.py` and
   `tasks/reprocess_task.py` pass it through.
6. **CLI + frontend**: `set --mic-track/--system-track`; the track picker on the uploaded
   Meeting page; the stale "a stereo file is split" copy in `UploadDialog`.
7. **Docs**: README, GLOSSARY (candidate track, track layout, mix), operator SKILL.md,
   `models/meeting.py` comment, ADR-0012 if it names the old behavior.
8. **Cleanup**: the old `probe["channels"] >= 2` test in `api/meetings.py` and the mocked
   probe schema in the three tests that patch `probe_audio`.

## Verify

| What | Command | Expected |
| --- | --- | --- |
| Backend | `pytest` from the repo root | all pass |
| Real ffmpeg | `pytest tests/test_analyze_tracks.py` (lavfi-generated files; skipped when ffmpeg is absent) | all pass |
| Frontend | `npm test` in `frontend/` | all pass |

## STOP conditions

- ffmpeg lacks the `pan` or `join` filter on this machine.
- Correlation thresholds misclassify the real OBS recordings the user has: report the
  numbers, do not tune blind.
