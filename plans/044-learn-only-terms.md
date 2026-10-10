# Plan 044: An edit teaches only term-like phrases, and learned forms wait for confirmation

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report; do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**: run
> `git diff --stat 31d4bae..HEAD -- transcript/vocabulary_correction.py transcript/segments.py tasks/vocabulary.py api/segments.py migrations/runner.py`.
> Any output is a STOP condition until compared with the excerpts below.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MEDIUM (it changes what is learned, and adds a data migration)
- **Depends on**: 014, 041
- **Category**: bug + design
- **Planned at**: commit `31d4bae`, 2026-10-10
- **Source**: the user, 2026-10-10, after seeing the learned Vocabulary:
  - "vamos pensar nessa regra que evite corrigir palavras comuns, ou até mesmo
    corrigir só se for alterado com frequência";
  - the decisions below were chosen from options the same day.

## Why this matters

Every manual edit teaches Vocabulary (`api/segments.py:update_segment_text`
calls `learn_from_edit` unless `learn=false`). The learned list held 105
entries, and most were not terms at all:
- markers: `[musica]`, `(Garrah falando)`;
- sentence fragments: `Ta ansioso?`, `pra dar na mão do cara.`;
- common words: `Obrigado.`, `prédio`, `hahaha`;
- bare numbers: `110`, `16`.

Some entries carried Misheard Forms that rewrite ordinary speech: `tu falou` →
`o valor`, `mente` → `medição`, and `Não, tem que ver` → `e tudo`. A form
corrects on its own after 2 sightings. When it does, the Correction is stored
as `confirmed: True`, because `rule == "misheard"`, so the page shows it as
already reviewed and hides the error.

## Decisions (with the user, 2026-10-10)

1. **An edit teaches only what looks like a term.** A changed or inserted
   phrase becomes a term, and a replaced phrase becomes its Misheard Form,
   only when one of these holds:
   - **Capital evidence**: after edge punctuation is stripped, every word is
     capitalized, an acronym, or a connector (`de`, `da`, `do`, `das`, `dos`,
     `e`); at least one word is capitalized or an acronym; and the capital
     evidence does not come only from a sentence-initial first letter.
     Sentence-initial means the phrase starts the edited text, or the Word
     before it ends in `.`, `?`, `!` or `…`. Examples that pass: `DWG`,
     `Pacaembu` (mid-sentence), `Outorga Onerosa`, `Faixa 3` (mid-sentence:
     a digit word counts as neither capital nor a blocker, but at least one
     capitalized word is required), `Habite-se`, `Louis Viton`. Examples that
     fail: `prédio`, `Obrigado` at the start of a sentence, `Ta ansioso`,
     `110`, `pra dar na mão do cara`;
   - **Known term**: the phrase, normalized, equals a term of the Meeting's
     Vocabulary (`parse_vocabulary(meeting.vocabulary)`) or a participant
     name (`meeting.participants`, comma or newline separated).

   The existing limits stay: length 2 to 99 characters, edge punctuation
   stripped, and an undone Correction teaches nothing.
2. **A learned form corrects after 2 sightings, as today, but stays up for
   review until the user confirms it once.** Each Misheard Form entry in
   `vocabulary_entries.misheard_as` gains `"confirmed": bool`.
   - The confirm route (`teach_confirmed_correction`, plan 041) sets it to
     `True`.
   - Learning from an edit leaves it as it is, or `False` for a new form.
   - At derivation, a `misheard` Correction stores `confirmed: True` only
     when its form is confirmed.
   - Eligibility is unchanged: `count >= 2`, or the term is in the Meeting's
     Vocabulary.
3. **Existing data.**
   - A numbered migration marks a form `confirmed: true` when any stored
     Correction with the same normalized `(heard, term)` has
     `confirmed: true`. Today these are the 30 the user confirmed in Meeting
     `3f332808`.
   - Cleaning the existing junk entries is not part of this plan. The
     orchestrator lists the entries that fail rule 1, shows them to the user,
     and deletes the approved ones through `DELETE /api/vocabulary/{id}`.

## Current state

- `transcript/vocabulary_correction.py`:

  ```python
  @dataclass(frozen=True)
  class MisheardForm:
      heard: str
      term: str
      count: int
  ...
  def learned_from_edit(
      before: str, after: str, *, undone: set[tuple[str, str]] = frozenset()
  ) -> tuple[list[str], list[tuple[str, str]]]:
      ...
      old_words, new_words = before.split(), after.split()
      for op, i1, i2, j1, j2 in SequenceMatcher(None, old_words, new_words).get_opcodes():
          new_phrase = " ".join(new_words[j1:j2]).strip(EDGE_PUNCTUATION)
          if not _worth_learning(new_phrase):
              continue
          if op == "insert":
              terms.append(new_phrase)
          elif op == "replace":
              ...
  def _worth_learning(phrase: str) -> bool:
      if not 2 <= len(phrase) < MAX_LEARNED_PHRASE_LENGTH:
          return False
      return not (phrase.islower() and len(phrase) < MIN_LOWERCASE_TERM_LENGTH)
  ```

  `_match_at` appends `(end, 2, form.term, "misheard")` for an eligible form,
  so it carries no flag today. Plan 041 made `derive_segments`
  (`transcript/segments.py:_stored_corrections`) set
  `"confirmed": item.rule == "misheard"`. `Correction` is a frozen
  dataclass `(start, end, heard, term, rule)`.
- `tasks/vocabulary.py`:
  - `load_misheard_forms(db)` builds `MisheardForm`s from
    `entry.misheard_as` items `{form, count}`;
  - `learn_from_edit(db, before, after, *, meeting_id, corrections)` calls
    `learned_from_edit`;
  - `teach_confirmed_correction` and `_record_misheard_form` (which
    increments `count` or appends `{form, count: 1}`).
- `bench/vocabulary_correction.py:125` calls
  `learned_from_edit(original["text"], edited.text)`. It must keep working;
  add the new arguments with defaults.
- `migrations/runner.py`: `_MIGRATIONS` is a tuple of
  `(version, name, statements)`. A statement is SQL or a callable taking the
  connection; see `_add_column`. The last version is 3.
- Tests:
  - `tests/test_vocabulary_correction.py` covers `learned_from_edit` directly,
    e.g. `learned_from_edit("o BWG, com", "o DWG, com")` and
    `("sem o habitese, hoje", "sem o Habite-se, hoje")`. Both must keep
    learning;
  - `tests/test_meeting_api.py:268`
    `test_segment_edits_learn_and_increment_misheard_form` covers the route;
  - `tests/test_vocabulary_tasks.py` has the processing table;
  - the migration test lives where plan 035 updated it to 3 migrations
    (`rg -n "migrations" tests/*.py`).

## Steps

Call the `tdd` skill first. The agreed seams are:
- `learned_from_edit`, which is pure;
- processing through the task harness, for the `confirmed` flag on stored
  Corrections;
- the edit and confirm routes, through the FastAPI test client;
- the migration, through the existing migration test pattern.

1. **Term gate.** In `tests/test_vocabulary_correction.py`, add a
   parametrized test of `learned_from_edit(before, after, known=())`
   returning terms and forms:
   - kept: `"o BWG, com"` → `"o DWG, com"`; mid-sentence
     `"fui no pai ru ontem"` → `"fui no Pacaembu ontem"`;
     `"a outorga onerosa"` → `"a Outorga Onerosa"`;
     `"no faixa 3 hoje"` → `"no Faixa 3 hoje"`;
   - dropped: `"e tu falou com"` → `"e o valor com"`;
     `"com a mente"` → `"com a medição"`; `"Obrigada."` → `"Obrigado."`
     (sentence-initial); `"foi 100"` → `"foi 110"`;
     `"[musica]"` → `"[música]"`;
   - known term: `"sem habitese"` → `"sem habite-se"` is kept with
     `known=("habite-se",)`, and dropped without `known` (it is lowercase).

   Then implement: a `known: Iterable[str] = ()` keyword on
   `learned_from_edit`, and `_looks_like_term(new_words, j1, j2, known)`
   replacing the capital-free branch of `_worth_learning`. Keep the length
   limits. Remove `MIN_LOWERCASE_TERM_LENGTH` if nothing else uses it.
2. **Known terms from the Meeting.** `tasks/vocabulary.learn_from_edit` loads
   the Meeting (`meeting_id`) and passes its Vocabulary terms and participant
   names as `known`. Test through `tests/test_meeting_api.py`: an edit to a
   lowercase term that is in the Meeting's Vocabulary is learned, and an edit
   of common words is not. Update
   `test_segment_edits_learn_and_increment_misheard_form` only if its phrases
   fail the gate. If they do, STOP, because the plan's examples assume they
   pass.
3. **Confirmed forms.**
   - `MisheardForm` gains `confirmed: bool = False`, and `load_misheard_forms`
     reads it with `item.get("confirmed", False)`.
   - `_record_misheard_form` keeps an existing flag and writes
     `"confirmed": False` for a new form. `teach_confirmed_correction` sets it
     `True`.
   - `_match_at` carries the form's flag. Either `Correction` gains a
     `confirmed: bool = False` field, or `apply` returns it another way;
     choose the smaller change. `_stored_corrections` stores it instead of
     `rule == "misheard"`.

   Tests:
   - a processed Segment with an unconfirmed eligible form (count 2) stores
     `confirmed: False`;
   - with the form confirmed, it stores `True`;
   - the confirm route marks the form confirmed (extend plan 041's confirm
     test).
4. **Migration 4**, "confirmed Misheard Forms from confirmed Corrections". A
   callable reads every Segment's `corrections` JSON, collects the normalized
   `(heard without edge punctuation, term)` of the confirmed entries, and
   sets `"confirmed": true` on the matching forms in
   `vocabulary_entries.misheard_as`. It must be idempotent and must leave
   unrelated forms untouched. Test it with the existing migration test
   pattern, and update the expected migration count to 4.
5. **Docs.**
   - `GLOSSARY.md`, Misheard Form: add one sentence saying it is learned only
     from edits that look like a term, and that it corrects on its own after
     two sightings but stays marked for review until the user confirms it.
   - `README.md`: if it describes learning from edits, align it.
   - In the operator skill, the "Learning and undo" section must still be
     true. Read it, and if a sentence becomes false, STOP and report the
     sentence; skill edits go through the orchestrator.
6. **Gates.** `uv run --extra dev pytest -q` from the root and `npm test` in
   `frontend/`. Both pass. Mark 044 DONE in `plans/README.md`.

## Hard boundaries

- In scope:
  - `transcript/vocabulary_correction.py`, `transcript/segments.py`
    (`_stored_corrections` only);
  - `tasks/vocabulary.py`, `migrations/runner.py`;
  - `bench/vocabulary_correction.py`, only if a signature change requires it;
  - the tests named above;
  - `GLOSSARY.md`, `README.md`, `plans/README.md`.
- Out of scope: the frontend, the operator skill, `api/` (no route change is
  needed), and deleting existing entries.
- Never touch `storage/`, the real database, `.env`, or the model-weight
  folders under `models/`. Never run the app, the CLI or the bench against
  real data.
- Every file change goes through the Edit and Write tools.

## STOP conditions

- The drift check prints changes.
- An existing test's learned phrase fails the new gate, and the fix would be
  to change its expected values.
- The operator skill states something the change makes false.

## Done criteria

- `uv run --extra dev pytest -q`: all pass.
- `cd frontend && npm test`: all pass.
- `rg -n "rule == \"misheard\"" transcript/segments.py`: no output.

## Maintenance note

The gate is a heuristic tuned to Portuguese transcripts with
Parakeet-style capitalization. A Transcriber that capitalizes nothing would
make every edit fail the capital test; then only known terms would teach.
That is the safe failure. The orchestrator runs the same rule over the
existing entries to propose a cleanup list for the user.
