# Plan 040: Vocabulary Correction stops swallowing neighbouring Words

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report; do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**: run
> `git diff --stat c3c8aae..HEAD -- transcript/vocabulary_correction.py tests/test_vocabulary_tasks.py tests/test_vocabulary_correction.py`.
> Any output is a STOP condition until compared with the excerpts below.

## Status

- **Priority**: P0 (it corrupts correct transcript text)
- **Effort**: S
- **Risk**: LOW (pure function, covered by a parametrized test table)
- **Depends on**: 014 (Vocabulary Correction)
- **Category**: bug
- **Planned at**: commit `c3c8aae`, 2026-10-10
- **Source**: the design survey for
  `.scratch/architecture-review/issues/08-correction-suggestions-ui.md`, run on
  2026-10-10 over every stored Correction (68 in 50 Meetings).

## Why this matters

Every one of the 68 Corrections stored today came from the `similar` rule.
42 of them changed text that was already right, by absorbing a neighbouring
Word into the term:

| Heard (Words matched) | Became | Segment text after |
|---|---|---|
| `o Henrique Marques,` | `Henrique Marques` | "Eu tenho Henrique Marques, que é…" (the article `o` is gone) |
| `da Brasil Urbano` | `Brasil Urbano` | the preposition `da` is gone |
| `na oferta terreno.` | `Oferta Terreno` | `na` is gone |
| `faixa 3. O` | `Faixa 3` | the sentence end `. O` is gone |
| `faixa 13` | `Faixa 3` | **a number changed** |

Trailing punctuation is fine: `_replacement_word` keeps it. The three defects
are in `_match_at`.

1. **A window that grows past the term still matches.** The term
   `henriquemarques` (15 letters) and the window `ohenriquemarques` (16)
   give a `SequenceMatcher` ratio of 2·15/31 = 0.968, above
   `SIMILAR_RATIO = 0.92`. Of the matches at one start, `max(...)` prefers the
   longest window, so the article goes too. The exact window
   `Henrique Marques` is skipped on purpose, because it is already spelled
   right; that leaves the longer, wrong window as the only candidate.
2. **A window crosses a sentence end.** Only a pause over
   `MAX_MERGE_GAP_SECONDS` stops a window from growing.
3. **Digits are compared like letters.** `faixa13` against `faixa3` is
   2·6/13 = 0.92, which passes.

## Decisions

The rules below apply to the `similar` rule only. The `misheard` rule matches
an exact learned form and stays as it is.

- **A window never matches when the same window minus its first Word, or
  minus its last Word, matches the term at least as well.** Measure with the
  same ratio. A dropped Word that leaves an exact (normalized) match also
  counts. This rejects `o Henrique Marques` and `da Brasil Urbano`. A
  shorter, correct window can still match at the next start position, so
  `na oferta terreno.` becomes `na Oferta Terreno.`
- **A window never spans a sentence end.** When any Word before the window's
  last Word ends in `.`, `?`, `!` or `…` (after stripping closing quotes and
  brackets), the window stops growing, the same way the pause rule `break`s.
- **Digits must match exactly.** The sequence of digits in the window's
  normalized text must equal the term's. `faixa 13` never becomes `Faixa 3`,
  and a window with digits never matches a term without them, or the
  reverse.
- The fixes are ordered by the cases they touch. Nothing else changes: the
  ratios, the phonetic key, `_window_limit`, or the preference for
  `misheard` over `similar`.
- Stored Meetings keep their current Corrections until the user runs
  Reapply Vocabulary. That is a data operation, so the orchestrator asks
  the user about it after the merge; it is not part of this plan.

## Current state

`transcript/vocabulary_correction.py`, `_match_at` (abridged; read the full
function before editing):

```python
        for end in range(start + 1, min(len(words), start + max_words) + 1):
            window = end - start
            if end > start + 1 and any(
                words[index].start - words[index - 1].end > MAX_MERGE_GAP_SECONDS
                for index in range(start + 1, end)
            ):
                break
            heard_norm = normalize_vocabulary_text("".join(word.text for word in words[start:end]))
            heard_spelling = _without_edge_punctuation(
                "".join(word.text for word in words[start:end])
            )
            ...
            for term in self.terms:
                ...
                term_norm = normalize_vocabulary_text(term)
                if len(_letters(term_norm)) < 4 or (
                    heard_norm == term_norm and heard_spelling == term
                ):
                    continue
                ratio = SequenceMatcher(None, heard_norm, term_norm).ratio()
                if (
                    ratio >= SIMILAR_PHONETIC_RATIO
                    and _phonetic_key("".join(word.text for word in words[start:end]))
                    == _phonetic_key(term)
                ) or ratio >= SIMILAR_RATIO:
                    matches.append((end, 1, term, "similar"))
        ...
        end, _, term, rule = max(matches, key=lambda item: (item[1], item[0]))
```

The behaviour is tested through processing in
`tests/test_vocabulary_tasks.py`: `test_vocabulary_correction_rules_seen_in_processed_segments`
is a `pytest.mark.parametrize` table of
`(words, vocabulary, misheard, expected_text, expected_terms)` with ids, using
`_spoken(*texts)` to build Words. Add rows to that table. Example row:

```python
        pytest.param(
            _spoken(" Garrah,", " confirmou."), "Vocabulary: Garrah",
            (), "Garrah, confirmou.", [],
            id="term-already-spelled-right-before-punctuation",
        ),
```

Check what `_spoken` does with timing first (`rg -n "def _spoken" -A8 tests/test_vocabulary_tasks.py`):
the Words must sit within `MAX_MERGE_GAP_SECONDS` of each other for a
multi-Word window to form.

## Steps

Call the `tdd` skill first. The agreed seam is the parametrized table above
(processing a Meeting through the task harness). Add one row, see it red,
make it green, then the next.

1. **Absorbed neighbour.** Add these rows:
   - `_spoken(" Eu", " tenho", " o", " Henrique", " Marques,")` with
     `"Vocabulary: Henrique Marques"` gives
     `"Eu tenho o Henrique Marques,"` and `[]`. Id:
     `a-neighbouring-article-is-never-absorbed`;
   - `_spoken(" da", " Brasil", " Urbano")` with `"Vocabulary: Brasil Urbano"`
     gives `"da Brasil Urbano"` and `[]`;
   - `_spoken(" na", " oferta", " terreno.")` with
     `"Vocabulary: Oferta Terreno"` gives `"na Oferta Terreno."` and
     `["Oferta Terreno"]`. Id: `the-term-is-fixed-without-its-neighbour`.

   Implement the trim rule. A small helper keeps `_match_at` readable, for
   example `_similar_ratio(heard_text, term) -> float | None`, which returns
   the ratio when the window passes the `similar` test, else None. Use it for
   the window and its trimmed variants.
2. **Sentence end.** Add the row `_spoken(" faixa", " 3.", " O")` with
   `"Vocabulary: Faixa 3"`, giving `"Faixa 3. O"` and `["Faixa 3"]`. Id:
   `a-window-never-crosses-a-sentence-end`. Implement the `break`.
3. **Digits.** Add the row `_spoken(" faixa", " 13")` with
   `"Vocabulary: Faixa 3"`, giving `"faixa 13"` and `[]`. Id:
   `digits-must-match-exactly`. Implement the digit check.
4. **No regressions.** Every existing row stays green unchanged, notably
   `adjacent-words-merge-and-keep-trailing-punctuation` (`Gar` + `rah,` →
   `Garrah,`) and `one-word-term-matches-at-most-two-words`. Run
   `uv run --extra dev pytest -q tests/test_vocabulary_tasks.py tests/test_vocabulary_correction.py tests/test_vocabulary_bench.py`.
5. **Docs.** In `GLOSSARY.md`, the Vocabulary Correction entry needs no
   change, since it does not describe matching rules. If
   `rg -n -i "similar|window|SIMILAR_RATIO" README.md docs/ --glob '!docs/adr/**'`
   finds prose describing how a `similar` match is chosen, add the three
   rules there in one sentence each. Otherwise change nothing.
6. **Gates.** `uv run --extra dev pytest -q` from the root and `npm test` in
   `frontend/`. Both pass. Mark 040 DONE in `plans/README.md`.

## Hard boundaries

- In scope: `transcript/vocabulary_correction.py` (`_match_at` and new
  private helpers), `tests/test_vocabulary_tasks.py`, docs from step 5, and
  `plans/README.md`.
- Out of scope: `tasks/vocabulary.py`, learning (`learned_from_edit`), the
  constants' values, `bench/`, and the frontend.
- Never touch `storage/`, the real database, `models/` or `.env`. Never run
  the app, the CLI or `bench.vocabulary_correction` against real data; the
  orchestrator runs the bench after the merge.
- Every file change goes through the Edit and Write tools.

## STOP conditions

- The drift check prints changes.
- An existing parametrized row has to change its expected values to pass.
- The trim rule rejects a case that the table expects to be corrected.

## Done criteria

- `uv run --extra dev pytest -q`: all pass, including the five new rows.
- `cd frontend && npm test`: all pass.

## Maintenance note

`bench/vocabulary_correction.py` measures hits and false changes against the
user's edits. After this plan the orchestrator compares its numbers before
and after on the real data. A future loosening of `SIMILAR_RATIO` must keep
the five new rows green; they encode the false changes seen in real Meetings.
