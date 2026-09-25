# Plan 014: Vocabulary Correction

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` and the status of
> `.scratch/architecture-review/issues/06-vocabulary-for-parakeet.md`.
>
> **Drift check (run first)**: `git diff --stat a066046..HEAD -- transcript/ tasks/ api/segments.py api/meetings.py models/segment.py models/vocabulary_entry.py models/job.py database.py preferences.py main.py frontend/src/pages/MeetingPage.tsx frontend/src/api.ts`
> If any in-scope file changed since this plan was written, compare the
> "Current state" notes against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

> **Local-only steps**: see "Run locally by the user" in `plans/README.md`. An agent
> stops before them, leaves their boxes unchecked, and never writes estimated numbers.

## Status

- **Execution**: IN PROGRESS — implementation through Step 4; local bench gate remains.

- **Priority**: P1 (the most-used Engine gets no Vocabulary today)
- **Effort**: L
- **Risk**: MED
- **Depends on**: plans 012 and 013 (done)
- **Category**: feature
- **Planned at**: commit `a066046`, 2026-09-24
- **Source**: design session 2026-09-24 on ticket 06
  (`.scratch/architecture-review/issues/06-vocabulary-for-parakeet.md`)

## Why this matters

parakeet.cpp is the Engine used most (ADR-0007) and ignores Vocabulary:
`engines/parakeet_cpp.py` discards it ("Parakeet takes no prompt"), and the
installed `mudler/parakeet.cpp` CLI has no biasing flag. Terms the user
supplies never reach it. On faster-whisper the Vocabulary is only a prompt
hint. Vocabulary Correction applies the Vocabulary after any Transcriber, as
a pure step of Segment derivation.

## Decisions (from the design session — do not re-litigate)

1. **Mechanism**: Engine-agnostic post-correction. Decoder biasing in
   parakeet.cpp and N-best re-ranking are out of scope.
2. **Where**: at Segment derivation (`transcript/`), after alignment. The
   stored `raw_transcription` Words stay as the Transcriber heard them.
3. **Which terms**:
   - Similarity matching only against **this Meeting's Vocabulary** (the
     `Speakers:` names and the `Vocabulary:` terms in `meeting.vocabulary`).
   - A learned **Misheard Form** applies when its term is in the Meeting's
     Vocabulary **or** it has been learned at least twice.
4. **Aggressiveness**: precision first. Missing a correction is better than
   a wrong one. Accent- and case-insensitive, spelling similarity plus a
   PT-BR phonetic key, terms shorter than 4 letters ignored, and adjacent
   Words may merge into one term ("Gar rah" → "Garrah"). On by default for
   every Engine, with a toggle in Preferences.
5. **No UI in this plan.** Suggestions on the Meeting page are ticket 08.
6. **Reprocessing**: every existing Reprocessing re-applies it (they rebuild
   Segments anyway), plus a new lightweight Reprocessing, "Re-apply
   Vocabulary", in the Meeting's Reprocess menu. Saving the Vocabulary does
   not trigger it automatically.
7. **Manual edits win.** An edited Segment keeps the user's text. Undoing a
   Correction by hand teaches nothing; false positives are fixed by deleting
   the term or Misheard Form in Settings.
8. **What gets stored**: a JSON column `segments.corrections` with
   `[{start, end, heard, term, rule}]` per Segment (`rule` is `"similar"` or
   `"misheard"`), recomputed on every rebuild. `[]` for edited Segments.
9. **Learning**: `_learn_from_correction` also records the replaced phrase as
   a Misheard Form of the new term.

Terms (`CONTEXT.md`): **Vocabulary Correction**, **Misheard Form**.

## Current state

- `transcript/segments.py::derive_segments(words, diarization, switch_penalty)`
  — Segment derivation entry point used by both tasks.
- `tasks/process_meeting.py`, `tasks/reprocess_task.py` — call
  `derive_segments`; `tasks/shared.py::rebuild_speakers_and_segments`
  persists the Segment dicts and preserves edited text by ±1.5 s.
- `meeting.vocabulary` — free text formatted by
  `frontend/src/utils/vocabulary.ts` as `Speakers: A, B` and
  `Vocabulary: t1, t2` lines; legacy unformatted text is all terms.
- `models/vocabulary_entry.py` — `term` (unique), `frequency`,
  `source_meeting_id`. `api/segments.py::_learn_from_correction` diffs
  `original_text` vs the edit and stores only the new phrase.
- `database.py::init_db` — `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` list.
- `preferences.py::_DEFAULTS` — preference keys with defaults.
- Reprocess menu: `frontend/src/pages/MeetingPage.tsx` ("Reprocess dropdown"),
  routes in `api/meetings.py` (`rediarize`, `reidentify`), tasks in
  `tasks/reprocess_task.py`, `JobType` in `models/job.py`.

## Target interface

```python
# transcript/vocabulary_correction.py  (pure: no DB, no config)
@dataclass(frozen=True)
class MisheardForm:
    heard: str
    term: str
    count: int

@dataclass(frozen=True)
class Correction:
    start: float
    end: float
    heard: str
    term: str
    rule: Literal["similar", "misheard"]

@dataclass(frozen=True)
class VocabularyCorrection:
    """Everything needed to correct one Meeting's Words."""
    terms: list[str]                  # this Meeting's Vocabulary
    misheard: list[MisheardForm]      # every learned form; eligibility is decided inside

    @classmethod
    def for_meeting(cls, meeting_vocabulary: str | None, misheard: list[MisheardForm]) -> "VocabularyCorrection": ...
    def apply(self, words: list[Word]) -> tuple[list[Word], list[Correction]]: ...
```

`derive_segments(words, diarization, switch_penalty=..., correction: VocabularyCorrection | None = None)`
applies the correction first and returns Segment dicts with an extra
`"corrections"` key (the Corrections whose time range falls inside the
Segment). `None` → no correction, `"corrections": []`.

Word rules for a replacement: keep the first Word's leading space and the
last Word's trailing punctuation (`"Galo,"` → `" Garrah,"`); `start` of the
first Word, `end` of the last, `confidence` and `alignment_score` = min of
the merged Words (None-safe).

## Steps

### Step 1: Pure correction module with tests

`transcript/vocabulary_correction.py`:

- `parse_vocabulary(text)` — mirror `parseVocabulary` in
  `frontend/src/utils/vocabulary.ts` (Speakers/Participantes and
  Vocabulary/Terms/Termos lines, legacy text = terms), split on `,`, `;`,
  newlines; dedupe case-insensitively.
- Normalization: NFKD, strip combining marks, casefold, strip punctuation.
- PT-BR phonetic key (keep it small and documented): drop `h` not in
  `ch/lh/nh`; `ç`/`ss`/`sc(e|i)`/`c(e|i)` → `s`; `qu(e|i)`/`c` → `k`;
  `g(e|i)`/`j` → `j`; `x`/`ch` → `x`; `z` between vowels → `s`; `w` → `v`;
  `y` → `i`; `ph` → `f`; collapse doubled letters.
- Matching windows: 1..(words in term + 1) consecutive Words, skipping
  windows that cross a gap > 0.5 s.
- Accept `similar` when the term has ≥ 4 normalized letters, the window is not
  already exactly the term, and either (a) normalized strings are equal
  (accent/case fix), or (b) `SequenceMatcher` ratio ≥ 0.85 **and** phonetic
  keys are equal, or (c) ratio ≥ 0.92. Put the thresholds in named constants
  with a comment that `bench/vocabulary_correction.py` tunes them.
- `misheard` rule: exact normalized match of a Misheard Form's `heard` to a
  window, eligible per decision 3. Misheard beats similar; longer window
  beats shorter; left to right, no overlapping replacements.

Tests `tests/test_vocabulary_correction.py`: parsing formatted and legacy
Vocabulary; "Galo" → "Garrah" via misheard (eligible and ineligible cases);
"Gar rah" merge; punctuation kept; accent/case fix; common word untouched
when no term is similar; 3-letter terms ignored; gap > 0.5 s blocks a merge;
Word timing/confidence rules; no correction returns the same Words.

**Verify**: `.\venv\Scripts\python.exe -m pytest tests/test_vocabulary_correction.py -q`

### Step 2: Wire into Segment derivation and persistence

- `derive_segments(..., correction=None)` as in "Target interface"; extend
  `tests/test_build_segments.py`.
- `models/segment.py`: `corrections: Mapped[list] = mapped_column(JSON, nullable=True)`;
  include in `to_dict` (default `[]`). `database.py::init_db`: add
  `"ALTER TABLE segments ADD COLUMN IF NOT EXISTS corrections JSON"`.
- `rebuild_speakers_and_segments`: write `seg.get("corrections", [])`, and
  `[]` when the Segment's text is preserved from an edit.
- `preferences.py`: `"vocabulary_correction": {"enabled": True}`; accept it
  in `main.py::update_preferences` (bool only).
- Both tasks build `VocabularyCorrection.for_meeting(meeting.vocabulary,
  <misheard forms from VocabularyEntry>)` when enabled, else `None`. Load the
  forms in one small helper next to the tasks (DB access stays out of
  `transcript/`).

**Verify**: task harness test (`tests/task_harness.py`) — a Meeting with
Vocabulary `Vocabulary: Garrah` and a Word " Garra" ends with a Segment text
containing "Garrah" and one stored Correction; with the preference off, no
change. Ordinary backend suite passes.

### Step 3: Learn Misheard Forms

- `VocabularyEntry.misheard_as: JSON` (list of `{"form": str, "count": int}`),
  migration line in `init_db`, included in `to_dict`.
- `_learn_from_correction`: on a `replace` op, record the old phrase
  (normalized for comparison, stored as typed) as a Misheard Form of the new
  term; increment `count` if present. Keep the existing term filters.
- Tests in `tests/test_services.py` or a new file: editing "Galo" to "Garrah"
  twice yields `{"form": "Galo", "count": 2}`.

### Step 4: "Re-apply Vocabulary" Reprocessing

- `JobType.REAPPLY_VOCABULARY = "reapply_vocabulary"`.
- `tasks/reprocess_task.py::reapply_vocabulary_task`: reuse stored Words and
  `MeetingDiarization.from_stored`, derive Segments with the correction, and
  rebuild **Segments only, keeping existing Speakers** (names, colors,
  identified_by). Add a variant of `rebuild_speakers_and_segments` or a flag;
  it must not reset user-renamed Speakers.
- `api/meetings.py`: `POST /{meeting_id}/reapply-vocabulary` with the same
  claim/enqueue shape as `reidentify` (do not refactor enqueue here; that is
  ticket 02).
- `frontend/src/api.ts` + the Reprocess dropdown in `MeetingPage.tsx`: one
  item "Re-apply vocabulary". Copy the existing item's classes.
- Tests: task test that Speakers keep their display names; API test that the
  route queues the task.

### Step 5: Bench

`bench/vocabulary_correction.py`: for every Meeting with edited Segments,
re-derive Segments from stored Words with and without correction, align the
derived Segments with the edited ones by time, and report per Meeting and in
total: tokens the user changed that the correction now gets right (hits),
tokens the correction changed that the user did not (false changes), and
tokens still wrong (misses). Output a table and a JSON file under
`bench/out/`. Document in `bench/README.md` how to run it against the local
database. Engine per Meeting comes from `raw_transcription["engine"]`.

The user runs this on ~8 edited Meetings (mostly parakeet.cpp). Tune the
Step 1 constants only from its results, and record the numbers in the plan
Outcome section.

## Commands you will need

| Purpose | Command | Expected |
|---------|---------|----------|
| Correction tests | `.\venv\Scripts\python.exe -m pytest tests/test_vocabulary_correction.py -q` | pass |
| Backend suite | `.\venv\Scripts\python.exe -m pytest tests -m "not model_load and not model_inference" -q` | pass |
| Frontend | `npm test` and `npm run build` in `frontend` | pass |
| Bench | `.\venv\Scripts\python.exe bench/vocabulary_correction.py` | table + JSON |

## Done criteria

- [x] `transcript/vocabulary_correction.py` imports nothing from `tasks`, `services`, `config`, `database`, `redis`
- [x] Stored `raw_transcription` Words are unchanged by correction
- [x] Corrections are stored per Segment and recomputed on every rebuild
- [x] Re-apply Vocabulary keeps Speaker names
- [ ] Bench numbers from the user's Meetings recorded in this plan
- [x] `plans/README.md` row and ticket 06 status updated
- [x] `CONTEXT.md`: drop the "(planned, plan 014)" markers and the "once plan 014 lands" wording

## STOP conditions

- Bench shows more false changes than hits on the user's Meetings with the
  starting thresholds and no single-constant change fixes it. Report the
  numbers; do not ship a correction that makes transcripts worse.
- Keeping Speakers on Re-apply requires changing how Speakers are keyed.
- Any need to change the Transcriber port or an Engine adapter.

## Maintenance notes

- Ticket 08 (suggestions on the Meeting page) reads `segments.corrections`.
- If decoder biasing is ever added to parakeet.cpp, keep this step: it also
  covers Misheard Forms and every other Engine.

## Outcome

- Steps 1–4 implemented and focused verification passed.
- Focused backend verification: 54 tests passed across Vocabulary Correction,
  task harness, meeting API, Segment derivation, and Preferences.
- Latest focused backend verification: 51 tests passed, including speaker
  attribution stats, API learning persistence, metadata-only bench output, and
  accent-only correction scoring.
- Frontend verification: 36 tests passed; `npm run build` passed.
- The bench script and run instructions are implemented; no user database was
  opened during this work.
- **Local bench gate still required:** run
  `.\venv\Scripts\python.exe bench/vocabulary_correction.py` on the user's edited Meetings;
  record its per-Meeting and total hits, false changes, and misses here. Do not
  mark this plan or ticket complete until that gate is reviewed.
