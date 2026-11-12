# Plan 025: Transcript edits are validated, reversible, and do not always teach Vocabulary

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report; do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat c5cc40a..HEAD -- api/segments.py api/speakers.py meeting_store.py tests/test_meeting_api.py`
> Plan 024 does not touch these files. Any drift is a STOP condition until you
> have compared it against the excerpts below.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW (additive routes; one existing route gains validation)
- **Depends on**: none (024 recommended first so `uv run pytest -q` works from the root)
- **Category**: bug, direction
- **Planned at**: commit `c5cc40a`, 2026-10-09
- **Source**: agent-friendliness audit, 2026-10-09. User decisions: agent edits
  do not teach Vocabulary by default; renaming does not create a Voice Profile.

## Why this matters

A coding agent will correct this transcript through the HTTP API (ADR-0010,
plan 024). Today the edit routes trust their input and cannot be undone:

- `PUT /api/segments/{id}/speaker` accepts any Speaker id. A Speaker from
  another Meeting is stored silently. A missing id raises an unhandled
  IntegrityError (SQLite foreign keys are ON), which surfaces as a 500. The
  Speakers' `segment_count` and `total_speaking_time` are not updated either,
  so the Speaker panel shows stale numbers.
- `PUT /api/segments/{id}` always runs `learn_from_edit`, so every text edit
  teaches Vocabulary and Misheard Forms that apply to *all future Meetings*.
  An agent cannot hear the audio, so its corrections are guesses. They must not
  become rules unless the user confirms them.
- A wrong edit cannot be undone, although `Segment.original_text` keeps the
  derived text.
- When the Diarizer put two people under one label, there is no way to add a
  Speaker. `merge` is the only Speaker operation, and it does the opposite.
- An edit made while a Job is processing the Meeting is silently lost or
  404s: Reprocessing deletes and recreates every Segment and Speaker
  (`meeting_store.rebuild_speakers_and_segments`).

## Current state

- `api/segments.py` (whole file is 62 lines). Relevant parts:

  ```python
  class UpdateSegmentTextRequest(BaseModel):
      text: str = Field(..., min_length=1, max_length=10000)

  @router.put("/segments/{segment_id}")
  def update_segment_text(segment_id: str, req: UpdateSegmentTextRequest, db: Session = Depends(get_db)):
      segment = db.query(Segment).filter(Segment.id == segment_id).first()
      if not segment:
          raise HTTPException(404, "Segment not found")

      old_text = segment.original_text or segment.text
      undone_candidates = list(segment.corrections or [])
      segment.text = req.text
      segment.is_edited = True
      # An edited Segment keeps the user's text, so it has no Corrections left.
      segment.corrections = []
      db.commit()

      learn_from_edit(
          db, old_text, req.text,
          meeting_id=segment.meeting_id, corrections=undone_candidates,
      )

      return segment.to_dict()


  @router.put("/segments/{segment_id}/speaker")
  def update_segment_speaker(segment_id: str, req: UpdateSegmentSpeakerRequest, db: Session = Depends(get_db)):
      segment = db.query(Segment).filter(Segment.id == segment_id).first()
      if not segment:
          raise HTTPException(404, "Segment not found")

      segment.speaker_id = req.speaker_id
      db.commit()
      return segment.to_dict()
  ```
- `api/speakers.py` `merge_speakers` already recomputes stats for one Speaker
  (lines 38–46 of that file):

  ```python
  stats = db.query(
      func.count(Segment.id),
      func.coalesce(func.sum(Segment.end_time - Segment.start_time), 0),
  ).filter(Segment.speaker_id == target.id).one()
  target.segment_count = stats[0]
  target.total_speaking_time = stats[1]
  ```
- `meeting_store.py` is the persistence module for Speakers and Segments
  ("Persistence operations for Meetings and their derived Segments."). It
  imports `SPEAKER_COLORS` from `services.speaker_id_service`.
- `models/speaker.py`: `label` (e.g. `SPEAKER_00`, `HOST`, `UNKNOWN`),
  `display_name`, `color`, `identified_by` (`"manual"`, `"voice_profile"`,
  `"host_track"`, or null), `segment_count`, `total_speaking_time`.
- `models/meeting.py`: `MeetingStatus` is `UPLOADED | PROCESSING | COMPLETED | FAILED`.
- `api/meetings.py` already has the 409 wording `ALREADY_PROCESSING = "Meeting is already being processed"`.
- `frontend/src/api.ts` calls `PUT /segments/{id}` with `{ text }` only, and
  must keep its current behavior: a UI edit is the user's own correction and
  still teaches.
- Glossary terms to use in names, messages, and comments: **Segment**,
  **Speaker**, **Meeting**, **Vocabulary**, **Misheard Form**, **Reprocessing**.

Test convention: API tests live in `tests/test_meeting_api.py` and use its
`db_session` fixture plus `TestClient(app)`. Model new tests on
`test_segment_edits_learn_and_increment_misheard_form` in that file.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| One file | `uv run pytest -q tests/test_meeting_api.py` | all pass |
| Backend gate | `uv run pytest -q tests` | 0 failures |
| Frontend gate | `npm test` in `frontend/` | all pass |

## Suggested executor toolkit

- Call the Skill tool with `tdd`: one red test per behavior below, then the code.

## Scope

**In scope**:
- `api/segments.py`
- `api/speakers.py`
- `meeting_store.py` (add one helper)
- `tests/test_meeting_api.py`

**Out of scope**:
- `frontend/` — the UI keeps sending `{ text }` and still learns. Plan 027
  adds live refresh.
- Keeping Speaker names or reassignments across Reprocessing: that is plan 028.
- `api/speaker_profiles.py`: renaming never creates a Voice Profile (user decision).

## Git workflow

- Branch: `advisor/025-safe-edits`
- Conventional commits, e.g. `fix(segments): reassigning a Segment checks its Speaker and updates the stats`.
- Do not push.

## Steps

### Step 1: One stats helper

In `meeting_store.py` add:

```python
def refresh_speaker_stats(db, speaker) -> None:
    """Recount a Speaker's Segments and speaking time from the rows that exist now."""
```

It runs the same aggregate `merge_speakers` runs today and sets both fields
(no commit). Change `merge_speakers` in `api/speakers.py` to call it instead of
the inline query.

**Verify**: `uv run pytest -q tests/test_meeting_api.py` → all pass (no behavior change).

### Step 2: Refuse edits while a Job runs

In `api/segments.py` add a small helper used by every mutating route in this
plan:

```python
def _require_editable(db, meeting_id: str) -> None:
    meeting = db.get(Meeting, meeting_id)
    if meeting is not None and meeting.status == MeetingStatus.PROCESSING:
        raise HTTPException(409, "Meeting is being processed; edit it when the Job finishes")
```

Call it in `update_segment_text`, `update_segment_speaker`, and every new route
below. In `api/speakers.py`, call the same check in `update_speaker` and
`merge_speakers`, using the Speaker's `meeting_id`. Import the helper from
`api/segments.py` rather than duplicating it.

**Verify**: new test `test_segment_edit_is_refused_while_the_meeting_is_processing` → 409.

### Step 3: Reassigning a Segment validates and recounts

In `update_segment_speaker`:
- 404 `"Speaker not found"` when `req.speaker_id` has no Speaker row.
- 400 `"Speaker belongs to another Meeting"` when the Speaker's `meeting_id`
  differs from the Segment's.
- Remember the previous `speaker_id`, assign, then `refresh_speaker_stats` for
  the previous Speaker (if any) and the new one, then commit.

**Verify**: tests
`test_reassigning_a_segment_updates_both_speakers_stats`,
`test_reassigning_to_a_speaker_of_another_meeting_is_rejected`,
`test_reassigning_to_a_missing_speaker_is_404` → pass.

### Step 4: `learn` flag on text edits

Add `learn: bool = True` to `UpdateSegmentTextRequest`. Call `learn_from_edit`
only when `req.learn` is true. Everything else in the route stays as it is.

**Verify**: test `test_segment_edit_with_learn_false_teaches_nothing` →
after `PUT {"text": "Garrah", "learn": false}` on a "Galo" Segment, the
`VocabularyEntry("Garrah")` has `misheard_as` unchanged and no new
`VocabularyEntry` rows exist. The existing learning test still passes.

### Step 5: Revert a Segment

Add `POST /api/segments/{segment_id}/revert`:
- 404 when the Segment is missing; `_require_editable`.
- 409 `"Segment has no edit to revert"` when `is_edited` is false or
  `original_text` is null.
- Set `text = original_text`, `is_edited = False`, keep `corrections = []`,
  commit, and return `segment.to_dict()`. Never call `learn_from_edit`.

Add a docstring stating that Correction marks come back on the next
Reapply Vocabulary, because the edit cleared them.

**Verify**: tests `test_revert_restores_the_derived_text`,
`test_revert_of_an_unedited_segment_is_409` → pass.

### Step 6: Add a Speaker to a Meeting

In `api/speakers.py` add a second router or a route on the existing one at
`POST /api/meetings/{meeting_id}/speakers`, body
`{"display_name": str}` (strip; 400 `"display_name is required"` when empty;
max 200 chars). Then:
- 404 `"Meeting not found"`; `_require_editable`.
- `label` = `MANUAL_1`, `MANUAL_2`, … — the first `MANUAL_n` not already used
  by a Speaker of that Meeting.
- `color` = `SPEAKER_COLORS[existing_speaker_count % len(SPEAKER_COLORS)]`.
- `identified_by = "manual"`, `segment_count = 0`, `total_speaking_time = 0.0`.
- Return `speaker.to_dict()` with status 200.

If you add a second `APIRouter` to `api/speakers.py`, register it in `main.py`
next to `app.include_router(speakers.router)`. That `main.py` line is the only
change allowed in `main.py`.

**Verify**: tests `test_add_speaker_gets_the_next_manual_label`,
`test_add_speaker_requires_a_name` → pass.

### Step 7: Gate

**Verify**: `uv run pytest -q tests` → 0 failures; `npm test` in `frontend/` → all pass.

## Test plan

New tests in `tests/test_meeting_api.py`, using `db_session` and `TestClient(app)`:

1. `test_segment_edit_is_refused_while_the_meeting_is_processing`: Meeting
   status PROCESSING. `PUT /api/segments/{id}` returns 409 and the text is unchanged.
2. `test_reassigning_a_segment_updates_both_speakers_stats`: two Speakers, A
   with two Segments (0–1 s, 1–3 s) and B with none. Move the 1–3 s Segment
   to B. A has count 1 and time 1.0; B has count 1 and time 2.0.
3. `test_reassigning_to_a_speaker_of_another_meeting_is_rejected` → 400, Segment unchanged.
4. `test_reassigning_to_a_missing_speaker_is_404`.
5. `test_segment_edit_with_learn_false_teaches_nothing`.
6. `test_revert_restores_the_derived_text`: edit, then revert. The text equals
   `original_text`, `is_edited` is false, and `GET /api/vocabulary` is the same
   before and after the revert.
7. `test_revert_of_an_unedited_segment_is_409`.
8. `test_add_speaker_gets_the_next_manual_label`: existing `MANUAL_1`. The
   new Speaker is `MANUAL_2` with `identified_by == "manual"`.
9. `test_add_speaker_requires_a_name`: `"   "` → 400.

## Done criteria

- [ ] `uv run pytest -q tests` exits 0 with the 9 new tests passing
- [ ] `npm test` in `frontend/` exits 0
- [ ] `rg -n "func.count\(Segment.id\)" api/` → no match (the aggregate lives in `meeting_store.py`)
- [ ] `git status` shows only in-scope files (plus `main.py` if Step 6 needed a router)
- [ ] `plans/README.md` row for 025 updated

## STOP conditions

- An existing test expects edits on a PROCESSING Meeting to succeed.
- The frontend relies on `PUT /segments/{id}/speaker` accepting a Speaker of
  another Meeting (`rg -n "updateSegmentSpeaker" frontend/src`; read the
  callers before deciding).
- `learn_from_edit`'s signature differs from the excerpt.

## Maintenance notes

- Plan 027 publishes a change event from each of these routes; plan 028 makes
  `MANUAL_n` Speakers and reassignments survive Reprocessing; plan 030's CLI
  sends `learn: false` unless the user passes `--learn`.
- Reviewer: check that the UI path (`{ text }` only) still teaches, and that
  `revert` never calls `learn_from_edit`.
