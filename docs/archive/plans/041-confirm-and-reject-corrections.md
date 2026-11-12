# Plan 041: Confirm or reject a Vocabulary Correction (backend, CLI, glossary)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report; do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**: confirm plan 040 is DONE in `plans/README.md`.
> Then run
> `git diff --stat 832fe14..HEAD -- transcript/ tasks/vocabulary.py api/segments.py api/vocabulary.py models/ transcriber_cli/ GLOSSARY.md`.
> Any output is a STOP condition until compared with the excerpts below.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MEDIUM (it changes the stored shape of `segments.corrections` and
  adds a table)
- **Depends on**: 014, 040
- **Category**: feature
- **Planned at**: commit `8713b75` plus plan 040, 2026-10-10
- **Source**: `.scratch/architecture-review/issues/08-correction-suggestions-ui.md`.
  The design was decided with the user on 2026-10-10 (see Decisions).

## Why this matters

Vocabulary Correction rewrites Words silently while Segments are derived. The
user cannot see a Correction, confirm it, or stop a wrong one from coming
back. Plan 042 builds the page. This plan builds what the page calls:
- character offsets, so the page can mark the corrected Word;
- a confirm action that teaches;
- a reject action that reverts the text and records a global exception;
- a list of exceptions the user can manage.

## Decisions (with the user, 2026-10-10)

1. **The page marks the corrected Word** and offers confirm and undo on it.
   The Review tab is not used; it stays for the agent's notes.
2. **Undo is global**: it reverts the text here and records that this heard
   form never becomes this term again, in any Meeting. The user can see and
   remove these exceptions later ("deixa uma forma de organizar essas
   exceções globais se mudar de ideia"). The Segment does not become
   `is_edited`.
3. **Confirm teaches the Misheard Form** (heard → term), as accepting a
   suggestion does. The mark turns neutral.
4. The glossary name for an exception is **Rejected Form**: a heard form the
   user said is not a Misheard Form of a term.

Technical decisions:
- **Stored Correction shape.** Each entry of `segments.corrections` gains
  three keys, set at derivation:
  - `text_start` and `text_end`: character offsets, in the Segment's `text`,
    of the term as written. The edge punctuation kept around it is excluded;
  - `confirmed`: `True` when the Correction came from the `misheard` rule (a
    learned form), else `False`.

  Old stored entries lack the keys until the Meeting's Vocabulary is
  reapplied. The orchestrator reapplies the affected Meetings after the
  merge.
- **Identity of a Correction**: its `start` time within the Segment,
  compared within `TIME_TOLERANCE` (1e-6, `api/segments.py`). Corrections
  inside one Segment never share a start.
- **Confirm** (`POST /api/segments/{id}/corrections/confirm`, body
  `{"start": float}`):
  - make sure a `VocabularyEntry` exists for the term (create it as
    `learn_from_edit` does, with `source_meeting_id`);
  - record the heard form, without edge punctuation, as a Misheard Form
    (`_record_misheard_form`);
  - set `confirmed: true` on that stored Correction, reassigning the list so
    the JSON column saves;
  - commit, `jobs.notify_meeting_changed`, and return the Segment dict.
- **Reject** (`POST /api/segments/{id}/corrections/reject`, body
  `{"start": float}`):
  - add a Rejected Form `(heard, term)` unless an equal one exists, compared
    by `normalize_vocabulary_text` on both sides;
  - remove a Misheard Form with the same heard form from the term's entry,
    if any;
  - replace `text[text_start:text_end]` with the heard form without edge
    punctuation, in both `text` and `original_text`;
  - drop that Correction and shift the offsets of later ones by the length
    difference;
  - commit, notify, and return the Segment dict.
  - Other Meetings keep their stored text until their next Reprocessing,
    which then honours the Rejected Form.
- **Both routes return 409** when:
  - a Job is processing the Meeting (`require_editable`);
  - the Segment `is_edited`;
  - no Correction starts at `start`;
  - for reject only, the entry lacks `text_start`. The message is "reapply
    Vocabulary first".
- **Rejected Forms are honoured by both rules.** `VocabularyCorrection`
  carries them, and `_match_at` discards any candidate (`similar` or
  `misheard`) whose normalized window equals a Rejected Form's heard form
  for that term.
- **Managing exceptions**:
  - `GET /api/vocabulary/rejected-forms` lists `{id, heard, term,
    source_meeting_id, created_at}`, newest first;
  - `DELETE /api/vocabulary/rejected-forms/{id}` removes one. The next
    Reprocessing corrects that form again.
- **CLI**:
  - `render.segment_line` shows a confirmed Correction as
    `[confirmed: heard->term]`, and an unconfirmed one keeps
    `[fixed: heard->term]`;
  - `suspects`' CORRECTED BY VOCABULARY lists only unconfirmed Corrections;
  - the CLI gets no confirm or reject command. The agent cannot hear, and
    confirming teaches.

## Current state

- `transcript/vocabulary_correction.py`:
  - `VocabularyCorrection(terms, misheard)` is a frozen dataclass with
    `for_meeting(meeting_vocabulary, misheard)`;
  - `apply(words)` returns `(words, corrections)`;
  - `_match_at` builds the candidates;
  - `_replacement_word(words, term)` builds the text
    `f"{leading}{term}{trailing}"`, where `leading` includes the Word's
    leading space;
  - `_without_edge_punctuation(spelling)` and `normalize_vocabulary_text`
    exist.

  Plan 040 changed `_match_at`; read its current version.
- `transcript/segments.py:derive_segments(words, diarization, switch_penalty, correction, splits)`:
  - corrects the Words, then calls `build_segments`;
  - attaches each Correction to the Segment whose `[start, end]` contains it,
    as a dict `{start, end, heard, term, rule}`;
  - a Segment's text is `"".join(w.text for w in words).strip()` (`_close`).
- `tasks/vocabulary.py`:
  - `vocabulary_correction_for_meeting(db, meeting, enabled)` loads the
    forms;
  - `learn_from_edit` creates entries;
  - `_record_misheard_form(db, heard, term)` increments or adds a form, and
    does nothing when no entry matches the term.
- `api/segments.py` has:
  - `require_editable(db, meeting_id)`;
  - `TIME_TOLERANCE`;
  - the route pattern to copy: `revert_segment_text` (load the Segment, 404,
    `require_editable`, 409, mutate, commit, `jobs.notify_meeting_changed`,
    return `segment.to_dict()`).
- `api/vocabulary.py` has `list_vocabulary`, `delete_entry` and
  `delete_misheard_form`.
- Models live in `models/*.py` and are registered in `models/__init__.py`.
  New tables are created by `Base.metadata.create_all` in `database.init_db`;
  `ReviewNote` (plan 032) was added that way, with no migration. Copy
  `models/review_note.py`'s style.
- `transcriber_cli/render.py:segment_line` appends
  `[fixed: heard->term]` per Correction. `transcriber_cli/suspects.py:corrected_segments`
  returns Segments with any Correction, and `cmd_suspects` prints one line per
  Correction.
- Tests to extend:
  - `tests/test_vocabulary_tasks.py`: the parametrized table, plus
    `test_each_correction_is_stored_on_the_segment_whose_time_contains_it`;
  - `tests/test_meeting_api.py` for routes (see the split route tests from
    plan 035 for the seeding helpers);
  - `tests/test_cli_suspects.py` and `tests/test_transcriber_cli.py` for the
    CLI.

## Steps

Call the `tdd` skill first. The agreed seams are:
- processing a Meeting through the task harness, for the stored Correction
  shape and Rejected Forms;
- the HTTP routes through the FastAPI test client;
- the CLI's pure functions and command output.

One test at a time, red then green.

1. **Offsets and `confirmed` at derivation.** Extend
   `test_each_correction_is_stored_on_the_segment_whose_time_contains_it`, or
   add a sibling test. A processed Segment whose text has a corrected term
   after other Words stores `text_start` and `text_end`, with
   `segment.text[text_start:text_end] == term`. Also cover:
   - a two-Word merge (`Gar` + `rah,`);
   - the term at the very start of the text, after `strip()` removed the
     leading space;
   - a `misheard`-rule Correction, which stores `confirmed: True`, while a
     `similar` one stores `False`.

   Compute the offsets in `derive_segments` from the same corrected Words the
   Segment's text is joined from. Do not search the text for the term, since
   the term can also occur uncorrected in the same Segment; add a test for
   that case.
2. **Rejected Form model and engine.**
   - Add `models/vocabulary_exception.py` with the class `RejectedForm`
     (table `rejected_forms`): `id`, `heard`, `term`, `source_meeting_id`
     (FK meetings, `SET NULL`) and `created_at`, plus `to_dict()`. Register
     it in `models/__init__.py`.
   - `VocabularyCorrection` gains `rejected: tuple[tuple[str, str], ...] = ()`
     of normalized `(heard, term)`. `for_meeting` takes it as an optional
     argument.
   - `vocabulary_correction_for_meeting` loads all Rejected Forms.
   - Test through the parametrized table, with a new `rejected` parameter,
     or a separate test if the table's signature would get awkward: a
     Rejected Form stops a `similar` match and a `misheard` match.
3. **Confirm route.** Tests: confirming teaches the form (the entry's
   `misheard_as` gains it, and the entry is created when missing), flips
   `confirmed`, and leaves the text unchanged. It returns 409 for an edited
   Segment and for an unknown `start`. Then implement.
4. **Reject route.** Tests:
   - the text and `original_text` revert at the offsets ("com Garrah, ontem"
     becomes "com Galo, ontem");
   - a later Correction's offsets shift;
   - the Rejected Form is stored once, even when rejected twice in two
     Meetings;
   - a Misheard Form with the same heard form is removed;
   - `is_edited` stays false;
   - 409 for a missing `text_start`;
   - after reject, `reapply_vocabulary_task` on the Meeting does not
     re-apply the Correction.

   Then implement.
5. **Rejected Forms routes.** Test list and delete, then implement them in
   `api/vocabulary.py`.
6. **CLI.** Tests: `segment_line` renders `[confirmed: …]` for a confirmed
   Correction; `corrected_segments` and the `suspects` output skip confirmed
   Corrections. Then implement.
7. **Docs.**
   - `GLOSSARY.md`: add **Rejected Form** after Misheard Form, in the
     glossary's style (a definition, plus `_Avoid_: exception, blocklist,
     stopword`). Extend Vocabulary Correction's entry with one sentence: the
     user confirms or rejects each one on the Meeting page.
   - `README.md`: if it lists API routes in a table, add the four new routes.
   - The operator skill needs no change, since the agent neither confirms nor
     rejects. Its CORRECTED BY VOCABULARY row still holds.
8. **Gates.** `uv run --extra dev pytest -q` from the root and `npm test` in
   `frontend/`. Both pass. Mark 041 DONE in `plans/README.md`.

## Hard boundaries

- In scope:
  - `transcript/vocabulary_correction.py`, `transcript/segments.py`
    (`derive_segments` only);
  - `tasks/vocabulary.py`, `api/segments.py`, `api/vocabulary.py`;
  - `models/vocabulary_exception.py`, `models/__init__.py`;
  - `transcriber_cli/render.py`, `transcriber_cli/suspects.py`;
  - the tests named above;
  - `GLOSSARY.md`, `README.md`, `plans/README.md`.
- Out of scope: the frontend (plan 042), `bench/`, and the skill.
- Never touch `storage/`, the real database, `.env`, or the model-weight
  folders under `models/` (only `models/*.py` source files). Never run the app,
  the CLI or the bench against real data.
- Every file change goes through the Edit and Write tools.

## STOP conditions

- The drift check prints changes.
- `derive_segments` cannot know which corrected Words make a Segment without
  changing `build_segments`' return shape.
- `create_all` does not create the new table in the test database.

## Done criteria

- `uv run --extra dev pytest -q`: all pass.
- `cd frontend && npm test`: all pass.
- `rg -n "Rejected Form" GLOSSARY.md`: one entry.

## Maintenance note

The offsets are only valid for the text derivation produced. Any route that
changes `segment.text` without re-deriving it must clear `corrections`. The
text edit route already does, because an edit leaves no Corrections. Plan 042
reads `text_start`, `text_end` and `confirmed`, so a rename of these keys
breaks the page.
