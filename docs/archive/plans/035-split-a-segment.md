# Plan 035: Split a Segment the Diarizer joined, and keep the split through Reprocessing

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report; do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat dd93f82..HEAD -- transcript/segments.py meeting_store.py api/segments.py tasks/reprocess_task.py tasks/process_meeting.py models/meeting.py migrations/runner.py transcriber_cli/`
> Any output is a STOP condition until compared with the excerpts below.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MEDIUM (touches Segment derivation, which every Reprocessing uses)
- **Depends on**: 025, 028, 029, 030 (all DONE)
- **Category**: feature
- **Planned at**: commit `dd93f82`, 2026-10-09
- **Source**: `.scratch/agent-operation/issues/02-split-segment.md`. The user
  asked for it on 2026-10-09 after reviewing two real Meetings: "o diarizador
  tende a separar a mesma pessoa e também juntar as falas em outros trechos
  ... talvez valesse a feature de tentar quebrar mais as falas que foram
  juntadas".

## Why this matters

When one Segment holds two people (a question and its answer on one line), the
only tools today are `assign`, which moves the whole Segment, and `edit`. Nothing
cuts a Segment. Cutting the row in the database alone is not enough: every
Reprocessing (Re-identify, Reapply Vocabulary, Re-diarize) deletes the Segments
and derives them again from Words + Turns, which would join the halves again.

## Decisions (settled 2026-10-09)

1. **A Split is a time stored on the Meeting**, in a new JSON column
   `meetings.split_times` (sorted list of seconds). Segment derivation always
   breaks a Segment there. Because the time does not depend on Turns, a Split
   survives Re-identify, Reapply Vocabulary **and** Re-diarize.
2. **A Split sits on a Word boundary.** The stored time is the `start` of the
   first Word of the second half. The API takes any time inside the Segment
   and snaps it to the nearest Word start (never the first Word: that is no
   cut).
3. **The second half can go to another Speaker in the same call.** That is a
   normal reassignment (`speaker_edited = True`), so it follows the existing
   plan-028 rules: re-applied on Re-identify and Reapply Vocabulary, dropped
   on Re-diarize (the Split itself stays).
4. **An edited Segment cannot be split** (409, "revert the edit first"): its
   text no longer maps to Words.
5. **`unsplit` undoes a Split**: it joins a Segment with the next one when a
   Split lies between them, and removes the stored time.
6. The CLI cuts by time (`--at`) or by the first Word(s) of the second half
   (`--before "Quem manda"`). The Meeting page gets no split control in this
   plan; plan 036 adds the split as a Review Note suggestion.
7. Tuning the Diarizer to switch more (the issue's second shape) is not part
   of this plan.

## Current state

- `transcript/segments.py`:
  - `build_segments(words, turns, switch_penalty)` attributes each Word to a
    Speaker, then walks the Words and starts a new Segment when
    `_breaks_before(current, word, speaker)` is true:

    ```python
    def _breaks_before(current: list[tuple[Word, str]], word: Word, speaker: str) -> bool:
        last_word, last_speaker = current[-1]

        if speaker != last_speaker:
            return True
        if last_word.text.rstrip().endswith(tuple(SENTENCE_ENDINGS)):
            return True
        if word.start - last_word.end > MAX_PAUSE_SECONDS:
            return True
        if word.end - current[0][0].start > MAX_SEGMENT_SECONDS:
            return True
        return False
    ```

  - `derive_segments(words, diarization, switch_penalty=..., correction=None)`
    applies Vocabulary Correction to the Words, calls `build_segments`, and
    attaches each Segment's `corrections` list. It returns
    `{start, end, text, speaker, confidence, corrections}` dicts. With
    `diarization=None` every Word is `"UNKNOWN"`. `bisect_right` is already
    imported.
- **Callers of `derive_segments`** that must pass the Meeting's Splits:
  - `tasks/reprocess_task.py`: `_reprocess_meeting` (Re-identify and
    Re-diarize) and `reapply_vocabulary_task`;
  - `tasks/process_meeting.py` (step 4).

  The bench scripts (`bench/*.py`) keep the default and are out of scope.
- `meeting_store.py`:
  - `rebuild_speakers_and_segments` and `replace_segments` carry edited text
    and reassignments by time range with `_claim_nearest` (tolerance
    `EDIT_TIME_TOLERANCE = 1.5` s on both start and end).
  - Halves that derivation recreates at the same times are matched exactly,
    so edits and reassignments on a half survive with no change here.
  - `refresh_speaker_stats(db, speaker)` recounts a Speaker.
- `api/segments.py` is the exemplar for the new routes:
  - `require_editable(db, meeting_id)` gives 409 while a Job processes the
    Meeting;
  - `update_segment_speaker` validates the Speaker (404 missing, 400 other
    Meeting), sets `speaker_edited`, refreshes both Speakers' stats, commits,
    and calls `jobs.notify_meeting_changed(meeting_id)` so the open Meeting
    page reloads live.
- `transcript/words.py`: `words_from_stored(meeting.raw_transcription)` gives
  the Meeting's Words in time order. Meetings from before the Transcriber
  port stored coarse segments; each becomes one long Word, so such a Segment
  usually has a single Word and cannot be split (409).
- `tasks/vocabulary.py`:
  `vocabulary_correction_for_meeting(db, meeting, *, enabled)`.
  `preferences.load().vocabulary_correction.enabled` is the current setting.
- `migrations/runner.py`: `_MIGRATIONS` holds numbered, idempotent steps.
  Migration 2 is `_add_column("segments", "speaker_edited", ...)`.
  `tests/test_database_sqlite.py::test_migration_2_adds_speaker_edited_to_an_existing_segments_table`
  builds an old database holding only a `segments` table and asserts
  `COUNT(*) FROM schema_migrations == 2`. Migration 3 adds a column to
  `meetings`, so that test must create a minimal `meetings` table too and
  expect 3.
- CLI (`transcriber_cli/main.py`):
  - `cmd_assign` is the exemplar: `load_meeting`, `resolve_segment(meeting, "#N")`;
    `new:NAME` creates a Speaker through `_add_speaker`;
  - `emit(args, data, lines)` prints JSON under `--json`, else text;
  - `segment_line` renders one Segment;
  - `parse_clock` parses `mm:ss(.s)` / `hh:mm:ss`.

  CLI tests in `tests/test_transcriber_cli.py` drive `main([...])` through the
  FastAPI TestClient (`api` fixture, `seed_meeting`, `add_speaker`,
  `add_segment`, `run`).
- Reprocessing tests: `tests/test_reprocess_keeps_edits.py` has a harness
  (`_processed`, `_run`, `_reassign`, `_owner_labels`) that runs the real
  Reprocessing tasks with fake Engines. Follow it.

## Scope

**In scope**:
- `transcript/segments.py`;
- `models/meeting.py` (column);
- `migrations/runner.py` (migration 3) and its test;
- `api/segments.py` (two routes);
- `tasks/reprocess_task.py` and `tasks/process_meeting.py` (pass the Splits);
- `transcriber_cli/main.py` (`split`, `unsplit`);
- tests;
- `GLOSSARY.md`, `README.md` (route table, Command line section);
- `.claude/skills/transcriber-operator/SKILL.md`.

**Out of scope**:
- the frontend;
- Review Notes (plan 036);
- `meeting_store.py`, unless Step 5's survival tests fail; then STOP;
- Diarizer settings;
- `bench/`.

## Git workflow

Branch `advisor/035-split-segment`. Commits, in order:
- `feat(segments): derivation honours Splits`;
- `feat(api): split and unsplit a Segment`;
- `feat(cli): split and unsplit`;
- `docs: Split`.

Do not push.

## Steps

### Step 1: Derivation breaks at Splits (TDD)

Add `splits: Sequence[float] = ()` to `build_segments` and `derive_segments`
(passed through). `_breaks_before` also returns True when a Split lies after
the last Word's start and at or before this Word's start:

```python
i = bisect_right(splits, last_word.start)
if i < len(splits) and splits[i] <= word.start:
    return True
```

`splits` must be sorted; sort once in `build_segments`.

Tests in `tests/test_build_segments.py`, written first and red:
- one Speaker, five Words with no pause or sentence end form one Segment;
  a Split at the third Word's start gives two Segments, with texts as
  literals;
- a Split time that is not a Word start (between two Words) breaks before
  the first Word starting after it;
- an empty `splits` changes nothing (an existing test already covers this;
  do not duplicate).

**Verify**: `uv run pytest -q tests/test_build_segments.py` passes.

### Step 2: The column and migration 3

- `models/meeting.py`: `split_times: Mapped[list] = mapped_column(JSON, nullable=True)`,
  with a one-line comment. Do not add it to `to_dict`.
- `migrations/runner.py`: migration
  `(3, "meeting split_times", (_add_column("meetings", "split_times", "JSON"),))`.
- Tests:
  - update the migration-2 test so its old database also has
    `CREATE TABLE meetings (id TEXT PRIMARY KEY)` and expects 3 rows;
  - add `test_migration_3_adds_split_times_to_an_existing_meetings_table` in
    the same shape.

**Verify**: `uv run pytest -q tests/test_database_sqlite.py` passes.

### Step 3: Reprocessing passes the Splits

In the three `derive_segments` calls listed in "Current state", pass
`splits=meeting.split_times or []`.

**Verify**: `uv run pytest -q tests/test_reprocess_keeps_edits.py tests/test_reprocess_dual_track.py` passes (no Splits yet, behavior unchanged).

### Step 4: `POST /api/segments/{segment_id}/split` and `/unsplit` (TDD)

Request model `SplitSegmentRequest(at: float, speaker_id: str | None = None)`.

`split_segment`:
1. 404 if the Segment is missing; `require_editable`; 409 `"revert the edit
   first"` if `segment.is_edited`.
2. The Segment's Words:
   - stored Words with `start >= segment.start_time - 1e-6` and
     `end <= segment.end_time + 1e-6`;
   - when a next Segment exists (`order + 1`), also `start < next.start_time`.
3. `correction = vocabulary_correction_for_meeting(db, meeting, enabled=preferences.load().vocabulary_correction.enabled)`.
   Snap: the cut is the `start` of the corrected Word nearest `at` among all
   corrected Words but the first. Apply the correction first, so a cut never
   falls inside a corrected multi-Word term. 409 `"this Segment has no Word
   boundary to cut at"` when there are fewer than two corrected Words.
4. `halves = derive_segments(words, None, correction=correction, splits=[cut])`.
   409 `"could not split here"` unless `len(halves) == 2`.
5. Validate `speaker_id` if given, exactly like `update_segment_speaker`
   (404 or 400).
6. Rows:
   - shift every later Segment of the Meeting: `order = order + 1` where
     `order > segment.order`;
   - the existing row becomes the first half: `end_time`, `text`,
     `original_text`, `confidence` and `corrections` come from `halves[0]`;
   - a new Segment for `halves[1]` at `order = segment.order + 1`, with the
     same Speaker, or `speaker_id` with `speaker_edited = True`. Without
     `speaker_id` it inherits `segment.speaker_edited`.
7. `meeting.split_times = sorted(set((meeting.split_times or []) + [cut]))`.
   Assign a new list; do not mutate the old one in place, or SQLAlchemy will
   not see the change.
8. Refresh stats for every Speaker involved, commit, `notify_meeting_changed`.
9. Return `{"segments": [first.to_dict(), second.to_dict()]}`.

`unsplit_segment`:
1. 404 when missing; `require_editable`.
2. 409 `"no Split after this Segment"` unless:
   - the next Segment (`order + 1`) exists;
   - a stored Split equals `next.start_time` within `1e-6`.
3. 409 `"revert the edit first"` if either Segment is edited.
4. Re-derive the joined Segment with
   `derive_segments(words_of_both, None, correction=correction)`, using the
   Words of both Segments and the same correction as in split. 409 unless it
   yields exactly one Segment.
5. Update the first row:
   - `end_time`, `text`, `original_text`, `confidence`, `corrections` from
     the joined Segment;
   - keep the first row's Speaker and `speaker_edited`.
6. Delete the second row; shift later Segments down by one.
7. Remove the Split from `split_times`, refresh stats, commit, notify, and
   return the joined `to_dict()`.

Tests in `tests/test_meeting_api.py`, each red first, using the
`db_session` fixture and seeding `raw_transcription` like the existing tests:
- a split at a mid-Word time snaps to the nearest Word start. Check:
  - the two texts;
  - later Segments' `order` shifted by one;
  - `split_times` stored.
- splitting with `speaker_id` puts the second half on that Speaker with
  `speaker_edited` true. Both Speakers' `segment_count` are right.
- 409 for an edited Segment, for a one-Word Segment, and while the Meeting
  is `PROCESSING`.
- `unsplit` after `split` restores one Segment with the original text and
  empties `split_times`. `unsplit` with no Split gives 409.

**Verify**: `uv run pytest -q tests/test_meeting_api.py` passes.

### Step 5: Splits survive Reprocessing (tests only)

In `tests/test_reprocess_keeps_edits.py`, with its harness, add:
- `test_a_split_survives_reidentify`: split a Segment through the route,
  run Re-identify, then check the same two texts at the same times.
- `test_a_split_survives_reapply_vocabulary`.
- `test_a_split_survives_rediarize_but_its_reassignment_does_not`.
- `test_a_split_second_half_reassignment_survives_reidentify`.

**Verify**: these pass with no change to `meeting_store.py`. If any fails,
STOP and report the failure.

### Step 6: CLI `split` and `unsplit`

- `split M #N (--at T | --before WORDS) [--speaker S|new:NAME]`, with
  exactly one of `--at` and `--before` required.
  - `--before` matches the Words as the Transcriber heard them, before
    Vocabulary Correction. Fetch them with
    `GET /api/meetings/{id}/words?start=&end=` over the Segment's range,
    keeping Words inside the Segment.
  - Normalize each Word and the phrase the same way: strip whitespace and
    the punctuation `.,;:!?…"'()[]`, then casefold.
  - Find every position `i >= 1` where the phrase's words match
    `words[i:i+k]`.
    - No match: exit 1 with `'WORDS' is not among #N's Words as heard; see
      \`words M --from .. --to ..\` or use --at`.
    - More than one: exit 1 and list each match's clock, asking for `--at`.
  - `at` is the matched Word's `start`.
  - `--speaker` resolves like `assign` (`new:NAME` creates the Speaker).
  - Print both halves with `segment_line`, then:
    `Segments after #N are renumbered (+1).`
- `unsplit M #N`: prints the joined Segment, then
  `Segments after #N are renumbered (-1).`
- Help texts state that a Split survives Reprocessing and that `--speaker`
  follows the reassignment rules.

Tests in `tests/test_transcriber_cli.py`, following the existing `assign`
tests:
- `--before` with a two-word phrase;
- `--before` not found exits 1;
- `--before` ambiguous exits 1;
- `--at`;
- `--speaker new:Carla`;
- `unsplit`.

**Verify**: `uv run pytest -q tests/test_transcriber_cli.py` passes.

### Step 7: Docs and skill

- `GLOSSARY.md`, under "Reviewing", after Review Note:

  ```markdown
  **Split**:
  A boundary the user forces inside a Segment, at the start of a Word. The Meeting keeps it, so
  every Reprocessing derives the Segments with that boundary; a Split survives even Re-diarize.
  _Avoid_: cut, break
  ```

- `README.md`: route table rows for the two routes, and the Command line
  section gains `split` and `unsplit` (match the existing rows).
- Skill: **invoke the `writing-for-agents` skill first and let it govern the
  edit**. In `.claude/skills/transcriber-operator/SKILL.md`, phase 3 (Name
  Speakers) gains a short rule after the `add-speaker`/`assign` paragraph:
  - when one Segment holds two people, `split M #N --before "first words"
    --speaker S`;
  - split only when the text shows the change of speaker (a question and
    its answer, a name addressed and then answering);
  - `show` again afterwards, because later handles shift.

  Add `split`/`unsplit` to the Commands line.

**Verify**: `rg -n "split" GLOSSARY.md README.md .claude/skills/transcriber-operator/SKILL.md` matches all three.

### Step 8: Gate

**Verify**: `uv run pytest -q` passes (expect the previous 528 passed and
20 skipped, plus the new tests). `cd frontend && npm test` passes
(unchanged).

## Done criteria

- [ ] The new tests in Steps 1, 4, 5 and 6 were red before the implementation and pass now
- [ ] `uv run pytest -q` and `npm test` pass
- [ ] `rg -n "splits=meeting.split_times" tasks/` matches 3 call sites
- [ ] `meeting_store.py` unchanged (`git diff --stat dd93f82..HEAD -- meeting_store.py` is empty)
- [ ] `plans/README.md` row for 035 updated

## STOP conditions

- Drift in the listed files.
- A Step 5 survival test fails: report it, do not change `meeting_store.py`.
- Snapping cannot be made to land on a boundary that `derive_segments`
  breaks at (e.g. corrected Words carry different starts than expected).
  Describe the case.

## Maintenance notes

- Plan 036 adds the `split` Review Note kind; it calls `split_segment`.
- A future Retranscribe replaces the Words; `split_times` then snaps to
  whatever new Word starts at or after each time. That is harmless, but a
  user may want them cleared: decide then.
- A Split reorders Segment handles (`#N`); anything holding a handle across
  a Split must re-read the Meeting.
