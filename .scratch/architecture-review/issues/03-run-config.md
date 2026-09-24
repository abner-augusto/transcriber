# 03 - Resolve Run Configuration Once per Job

**Source:** architecture review 2026-09-24, candidate 5.

**What to build:** One module that resolves the Preset, `preferences.json`,
and environment `Settings` into a typed, validated `RunConfig` snapshot at
Job start, stored with the Job for provenance and handed to the adapters.

**Why:** The three config sources are merged in four places:
`engines/__init__.py` (whisper DTW), `tasks/process_meeting.py` (forced
alignment, including the bool-or-dict shape), `engines/pyannote.py`
(re-reads `preferences.json` on every call for clustering overrides), and
`services/speaker_id_service.py`. Validation of preferences lives in
`main.py::update_preferences` while vocabulary profiles live in
`api/preferences.py`. A Job does not record the configuration it actually ran
with.

**Blocked by:** None — can start any time; easier after ticket 01.

**Status:** ready-for-agent

**Plan:** `plans/016-one-place-for-preferences-and-run-config.md` (design session 2026-09-24:
one `Preferences` model and one file in storage, `.env` only for machine facts, RunConfig
resolved at Job start and stored on the Job, Engines configured through factories).

**Open questions for the exploration session:**
- Snapshot on enqueue (API) or on run (worker)? Enqueue makes retries
  reproducible; run picks up late slider changes.
- Store on `Job` (new JSON column) or inside `raw_transcription` /
  `raw_diarization`?
- Should `preferences.json` become a DB table as part of ticket 05?

**Acceptance criteria (draft):**
- [ ] Engines and services no longer call `load_preferences()`
- [ ] One validation function for every preference the UI can set
- [ ] Each finished Job exposes the RunConfig it used
