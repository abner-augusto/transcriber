# Plan 028: Speaker names and Segment reassignments survive Reprocessing

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report; do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat c5cc40a..HEAD -- meeting_store.py tasks/reprocess_task.py tasks/process_meeting.py models/segment.py migrations/runner.py api/segments.py api/speakers.py`
> Plan 025 is expected to have added `refresh_speaker_stats` to
> `meeting_store.py` and changed `api/segments.py`/`api/speakers.py`; plan 027
> adds `notify_meeting_changed` calls. Any other drift is a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED (touches the rebuild path every Job ends in; adds a column)
- **Depends on**: plan 025 (`refresh_speaker_stats`, `MANUAL_n` Speakers, validated reassignment)
- **Category**: bug
- **Planned at**: commit `c5cc40a`, 2026-10-09
- **Source**: `.scratch/architecture-review/issues/12-reprocessing-resets-speaker-names.md`
  (needs-exploration). The design questions were answered by the user on
  2026-10-09; the answers are the Decisions below.

## Why this matters

The agent workflow (ADR-0010) names the Speakers that no Voice Profile
matched, and moves Segments the Diarizer gave to the wrong person. Today any
Reprocessing throws that work away. `rebuild_speakers_and_segments` deletes
every Speaker and recreates them from the Speaker Namer, so the names fall
back to "Participant N". `replace_segments` (Reapply Vocabulary) keeps the
Speakers but recreates the Segments from the derived labels, so every manual
reassignment is undone. The user would have to re-check the whole Meeting
after every Re-identify, which is the very step the workflow suggests after
saving a Voice Profile.

## Decisions (do not re-litigate)

1. **Re-identify and Reapply Vocabulary** keep the Turns, so labels are stable.
   A Speaker with `identified_by == "manual"` keeps its `display_name` **by
   label**, and the name wins over a Voice Profile match.
2. **Re-diarize and full processing of an already-processed Meeting** produce
   new Turns, so labels are not stable. A manual name moves to the new Speaker
   chosen **by Turn overlap**. Old Speaker O and new label N are a pair when N
   is O's best match, O is N's best match, and their shared speaking time is at
   least 50% of O's speaking time. Speaking time is measured from Segment
   intervals: O's Segments before the rebuild, N's derived Segments after.
3. The dual-track `HOST` label is deterministic (mic track): its manual name
   always carries by label, in every mode.
4. **Segment reassignments** (a Segment moved by hand to another Speaker,
   including by merge) are re-applied after Re-identify and Reapply
   Vocabulary. A new Segment takes the override when its start and end are
   within `EDIT_TIME_TOLERANCE` of the old one's, the same rule edited text
   already uses, and the target label exists. After Re-diarize they are
   dropped, because a new diarization is the user asking to redo who spoke when.
5. `MANUAL_n` Speakers (plan 025) are recreated with their name and color
   after Re-identify and Reapply Vocabulary. After Re-diarize they are not
   recreated, but their names can still carry to a new label through Decision 2.
6. After overrides are applied, Speaker stats are recounted from the final
   Segments. A *diarized* Speaker left with no Segments is deleted (commit
   `51c2037`: "a diarized label with no Segments is not a Speaker"). A
   `MANUAL_n` Speaker is kept even when it has no Segments.
7. Renaming never creates a Voice Profile, and the UI shows no warning. Both
   are out of scope.

## Current state

- `meeting_store.py`:

  ```python
  # An edited Segment survives a rebuild when a derived Segment starts and ends
  # within this many seconds of it.
  EDIT_TIME_TOLERANCE = 1.5

  def rebuild_speakers_and_segments(db, meeting, aligned, speaker_info, speaker_id_service):
      """Replace the Meeting's Speakers and Segments, preserving edited Segment text."""
      edited = _edited_segments(db, meeting)
      db.query(Segment).filter(Segment.meeting_id == meeting.id).delete()
      db.query(Speaker).filter(Speaker.meeting_id == meeting.id).delete()
      db.commit()

      speakers = {}
      for i, (label, info) in enumerate(sorted(speaker_info.items())):
          speaker = Speaker(
              meeting_id=meeting.id, label=label, display_name=info["name"],
              color=speaker_id_service.get_color(i),
              identified_by=info.get("identified_by"), confidence=info.get("confidence"),
          )
          ...
      # an "UNKNOWN" Speaker is added when any aligned segment has speaker "UNKNOWN"
      _write_segments(db, meeting, aligned, speakers, edited)

  def replace_segments(db, meeting, aligned):
      """Replace the Meeting's Segments, keeping its Speakers and edited Segment text."""
  ```

  `_write_segments` sets each Speaker's `segment_count`/`total_speaking_time`
  from `aligned`, not from the rows it wrote.
  `aligned` is a list of dicts with keys `start`, `end`, `text`, `speaker`
  (a label), `confidence`, `corrections`.
- Callers:
  - `tasks/process_meeting.py:114`: `rebuild_speakers_and_segments(db, meeting, aligned, speaker_info, speaker_id_service)`
  - `tasks/reprocess_task.py:73`: the same call, inside `_reprocess_meeting(current, rerun_diarization)`
    (Re-diarize when `rerun_diarization` is true, Re-identify otherwise)
  - `tasks/reprocess_task.py:125`: `replace_segments(db, meeting, aligned)` (Reapply Vocabulary)
- `models/segment.py` has no record of a manual reassignment. `is_edited`
  covers text only.
- `migrations/runner.py` runs numbered migrations whose statements are SQL
  strings, and requires every statement to be idempotent ("a migration
  interrupted before it is recorded is simply applied again"). On a fresh
  database `Base.metadata.create_all` runs first (`database.init_db`), so a new
  model column already exists and a plain `ALTER TABLE ... ADD COLUMN` would
  fail with "duplicate column".
- After plan 025: `PUT /api/segments/{id}/speaker` validates and recounts;
  `POST /api/meetings/{id}/speakers` creates `MANUAL_n` Speakers;
  `meeting_store.refresh_speaker_stats(db, speaker)` exists.
- Test harness: `tests/task_harness.py` `install(...)` gives a fake
  Transcriber and Diarizer over a temp SQLite file. `harness.diarizer.result`
  is the `DiarizationResult` the fake Diarizer returns, so a test can swap it
  between runs. The exemplar is `tests/test_reprocess_dual_track.py`
  (`_processed` helper, then `reidentify_task`/`rediarize_task`).

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Focus | `uv run pytest -q tests/test_speaker_carry.py tests/test_reprocess_keeps_edits.py tests/test_database_sqlite.py` | all pass |
| Backend gate | `uv run pytest -q tests` | 0 failures |
| Frontend gate | `npm test` in `frontend/` | all pass |

## Suggested executor toolkit

- Call the Skill tool with `tdd`. Write the pure matcher (Step 2) test-first,
  then one integration test per Decision.

## Scope

**In scope**:
- `models/segment.py` (one column + `to_dict` key)
- `migrations/runner.py` (callable statements + migration 2)
- `transcript/speaker_carry.py` (create)
- `meeting_store.py`
- `tasks/reprocess_task.py`, `tasks/process_meeting.py` (pass the mode only)
- `api/segments.py` and `api/speakers.py` (set the new flag on reassign and merge)
- `tests/test_speaker_carry.py`, `tests/test_reprocess_keeps_edits.py` (create), `tests/test_database_sqlite.py`
- `.scratch/architecture-review/issues/12-reprocessing-resets-speaker-names.md` (status line)
- `GLOSSARY.md` "Reprocessing" entry (one sentence)

**Out of scope**: Voice Profiles, the frontend, `transcript/segments.py`
(Segment derivation), the Diarization stage.

## Git workflow

- Branch: `advisor/028-edits-survive-reprocessing`; commits such as
  `feat(segments): remember a manual Speaker reassignment`,
  `fix(reprocessing): keep manual Speaker names (issue 12)`.
- Do not push.

## Steps

### Step 1: `Segment.speaker_edited` and migration 2

- `models/segment.py`: `speaker_edited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="0")`; add `"speaker_edited": self.speaker_edited` to `to_dict`.
- `migrations/runner.py`: let a statement be either a SQL string or a
  callable taking the connection. In `upgrade`, run
  `statement(connection) if callable(statement) else connection.exec_driver_sql(statement)`.
  Add a helper:

  ```python
  def _add_column(table: str, column: str, ddl: str):
      """An idempotent ADD COLUMN: SQLite has no IF NOT EXISTS for columns."""
      def apply(connection):
          existing = {row[1] for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")}
          if column not in existing:
              connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
      return apply
  ```

  Append migration `(2, "segment speaker_edited", (_add_column("segments", "speaker_edited", "BOOLEAN NOT NULL DEFAULT 0"),))`.

**Verify**: new test in `tests/test_database_sqlite.py`,
`test_migration_2_adds_speaker_edited_to_an_existing_segments_table`. Create
a `segments` table without the column (raw SQL with the minimal columns), run
`upgrade(engine)` twice, and assert the column exists with no error. The
existing fresh-database test still passes.

### Step 2: Pure overlap matcher

Create `transcript/speaker_carry.py`:

```python
"""Which new Speaker label inherits a name the user gave an old one, after new Turns."""

Interval = tuple[float, float]

def match_by_overlap(
    old: dict[str, list[Interval]],
    new: dict[str, list[Interval]],
    *, min_share: float = 0.5,
) -> dict[str, str]:
    """Map old label -> new label for mutual best matches sharing >= min_share of the old label's time."""
```

Shared time is the total intersection between the two interval lists. An old
label with zero speaking time matches nothing. Ties: the alphabetically first
label wins, so the result is deterministic.

**Verify**: `uv run pytest -q tests/test_speaker_carry.py` passes these cases:
identical intervals with swapped label names map across; a 40% overlap does
not match; two old labels competing for one new label match only the mutual
best; empty inputs give `{}`.

### Step 3: Snapshot before the rebuild, carry after

In `meeting_store.py`:

- Add a `keep` keyword to `rebuild_speakers_and_segments`:
  `keep: Literal["labels", "overlap"]` (no default, so every caller chooses).
- Before deleting rows, read:
  - manual Speakers: `label`, `display_name`, `color`, and their Segment
    intervals, for every Speaker with `identified_by == "manual"`;
  - reassignments: `(start_time, end_time, target_label)` for Segments with
    `speaker_edited`.
- After creating the new Speakers from `speaker_info`:
  - `"labels"`: for each manual snapshot whose label exists, set
    `display_name` and `identified_by = "manual"`. Recreate missing
    `MANUAL_n` labels as Speakers with their name and color.
  - `"overlap"`: `HOST` carries by label. For the rest, build `new` intervals
    from `aligned` grouped by `speaker` (skip `"UNKNOWN"`), call
    `match_by_overlap`, and copy the name with `identified_by = "manual"`.
- Write the Segments (`_write_segments`). Then, in `"labels"` mode only,
  re-apply reassignments: for each written Segment, find a snapshot override
  within `EDIT_TIME_TOLERANCE` on both ends whose target label is among the
  Meeting's Speakers. Point the Segment at that Speaker and set `speaker_edited = True`.
- Recount every Speaker with `refresh_speaker_stats`. Delete Speakers with zero
  Segments unless their label starts with `MANUAL_`. Commit.

Give `replace_segments` the same reassignment re-application and recount,
since it always runs in label mode. Extract one private helper used by both
functions; do not duplicate the loop.

**Verify**: integration tests from the Test plan pass.

### Step 4: Callers pass the mode

- `tasks/reprocess_task.py` `_reprocess_meeting`:
  `keep="overlap" if rerun_diarization else "labels"`.
- `tasks/process_meeting.py`: `keep="overlap"`. A first run has no manual
  Speakers, so this is a no-op there. A full re-run of a processed Meeting gets
  new Turns.

**Verify**: `uv run pytest -q tests` → 0 failures.

### Step 5: Routes set the flag

- `update_segment_speaker` (`api/segments.py`): set `segment.speaker_edited = True`.
- `merge_speakers` (`api/speakers.py`): in the bulk update, set
  `{"speaker_id": target.id, "speaker_edited": True}`.

**Verify**: the merge-then-reidentify integration test passes.

### Step 6: Records

- Issue 12 file: change `**Status:** needs-exploration` to
  `**Status:** done (plan 028)` and add one line under it naming the decisions.
- `GLOSSARY.md` "Reprocessing": append the sentence
  "Names the user gave Speakers survive it: by label when the Turns are kept, by Turn overlap when they are new."

**Verify**: `rg -n "Status:\*\* done \(plan 028\)" .scratch/architecture-review/issues/12-reprocessing-resets-speaker-names.md` → one match.

## Test plan

`tests/test_speaker_carry.py`: the Step 2 cases.

`tests/test_reprocess_keeps_edits.py` (model on `tests/test_reprocess_dual_track.py`):

1. `test_reidentify_keeps_a_manual_name`: process; set `SPEAKER_00`'s
   `display_name="Maria"` and `identified_by="manual"` in the DB; reidentify.
   `SPEAKER_00` is still Maria/manual.
2. `test_rediarize_moves_a_manual_name_to_the_overlapping_label`: process;
   name `SPEAKER_00` Maria; set `harness.diarizer.result` to the same Turns
   with labels swapped (`SPEAKER_00` ↔ `SPEAKER_01`, in `turns` and
   `exclusive_turns`); rediarize. Maria is now on `SPEAKER_01`.
3. `test_rediarize_drops_a_name_without_enough_overlap`: the new Turns give
   the old Speaker's time to two labels, about 50/50 minus a margin. Neither
   gets the name.
4. `test_reidentify_reapplies_a_segment_reassignment`: move one Segment to
   the other Speaker through `PUT /api/segments/{id}/speaker`, or directly in
   the DB with `speaker_edited=True`; reidentify; the Segment at the same
   times still belongs to the target Speaker.
5. `test_reapply_vocabulary_reapplies_a_segment_reassignment`: the same,
   through `reapply_vocabulary_task`.
6. `test_rediarize_drops_reassignments`.
7. `test_manual_speaker_survives_reidentify`: a `MANUAL_1` Speaker owning one
   reassigned Segment. After reidentify it exists with the same name and owns
   that Segment.
8. `test_stats_are_recounted_after_overrides`: after test 4's scenario, each
   Speaker's `segment_count` equals its actual number of Segment rows.

## Done criteria

- [ ] `uv run pytest -q tests` exits 0 with all new tests passing
- [ ] `npm test` in `frontend/` exits 0
- [ ] `rg -n "rebuild_speakers_and_segments\(" tasks/` → every call passes `keep=`
- [ ] Issue 12 status updated; GLOSSARY sentence added
- [ ] `plans/README.md` row for 028 updated

## STOP conditions

- Plan 025 is not DONE.
- A dual-track test in `tests/test_reprocess_dual_track.py` starts failing
  (HOST naming must be unchanged unless the user renamed HOST).
- `aligned` items do not carry `speaker`, `start` and `end` keys as described.
- Migration 2 cannot be made idempotent with the helper (e.g. the runner
  executes inside a transaction that rejects PRAGMA). Report the error.

## Maintenance notes

- The 50% threshold and the mutual-best rule live in one function
  (`match_by_overlap`). Tune them there if real Meetings show misses.
- Any new Reprocessing kind must pick a `keep` mode. "Do the Turns change?" is
  the question.
- Reviewer: check that a Voice Profile match never overrides a manual name in
  label mode, and that `MANUAL_n` Speakers are never deleted for being empty.
