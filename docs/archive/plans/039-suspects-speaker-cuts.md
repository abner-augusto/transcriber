# Plan 039: `suspects` lists sentences cut by a change of Speaker

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report; do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**: run
> `git diff --stat ceb9945..HEAD -- transcriber_cli/ tests/test_cli_suspects.py tests/test_transcriber_cli.py .claude/skills/transcriber-operator/SKILL.md README.md`.
> Any output is a STOP condition until compared with the excerpts below.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: 029, 030 (CLI and `suspects`)
- **Category**: feature (agent operation)
- **Planned at**: commit `ceb9945`, 2026-10-10
- **Source**:
  - the user, 2026-10-10 ("3. pode planejar");
  - the bench in `.scratch/agent-operation/issues/02-split-segment.md`,
    section "Bench, 2026-10-10".

## Why this matters

The Diarizer's most common error in the user's Meetings is a Speaker
boundary shifted by 1 to 3 Words at a handoff, in both directions. One
person's sentence ends as a tiny Segment of the next person, or the next
person's first Words stay with the previous one. The bench showed that no
global setting fixes these: `speaker_switch_penalty`, the Nemotron speech
threshold, raw Turns and a time offset each fix some and break others. They
stay an operator fix (`assign`).

Today the operator finds them by reading the whole transcript. In the Sinop
Meeting (658 Segments), 17 Segments were corrected by hand.

The calibration below found a cheap, accurate signal. Segment derivation
breaks a Segment at a sentence end, a pause over 1 s, the 30 s limit, or a
change of Speaker. So two consecutive Segments of different Speakers, less
than 1 s apart, where the first does not end a sentence, mean the Speaker
changed in the middle of a sentence. The transcriber (Parakeet) punctuates,
so this is visible in the text alone.

Calibration on Sinop's Segments as derived, before any hand correction:

| Rule | Pairs flagged | Pairs touching a hand fix | Hand-fixed Segments found |
|---|---|---|---|
| a short Segment (≤3 Words) next to another Speaker | 105 | about 10% | 11 of 17 |
| **a sentence cut by a change of Speaker (this plan)** | **29** | **16 (55%)** | **14 of 17** |

Most of the 13 other pairs were also worth a look. They include a split the
operator had already proposed as a Review Note, and two boundaries it had
left as ambiguous.

## Decisions

- A new, fourth section in `suspects` text output, after CORRECTED BY
  VOCABULARY. Its title is `SENTENCE CUT BY A SPEAKER CHANGE`.
- The rule, for Segments in `order`:
  - `a` and `b` are consecutive (`b.order == a.order + 1`);
  - their `speaker_id`s differ, and both are set;
  - `b.start_time - a.end_time <= 1.0`. Name the constant `CUT_MAX_GAP = 1.0`
    and say in its comment that it mirrors derivation's `MAX_PAUSE_SECONDS`.
    The CLI imports nothing from the app; it is a stdlib client;
  - `a.text`, stripped, does not end with one of `.?!…`;
  - neither Segment has `speaker_edited`. A person already decided who said
    it, so a reviewed handoff stops showing up.
- `a.text` is not checked for edits: an edited text still carries its
  punctuation.
- The pure function returns `{"first_order": a.order, "second_order": b.order,
  "gap": round(gap, 2)}` entries in Meeting order. JSON output (`--json`)
  adds them under the key `"speaker_cuts"`.
- One text line per pair, so `_section`'s indentation and `--limit` work
  unchanged:

  ```
  #68 02:31 Abner Augusto: "…É, tá" | #69 Valdomiro Garrah: "errado aqui, capitão."
  ```

  - First Segment: `segment_line`'s `#order clock who:` prefix, then its text
    quoted. If the text is longer than 60 characters, keep only its last 60,
    prefixed with `…`.
  - Second Segment: `#order who:`, then its text quoted. If longer than 60
    characters, keep its first 60 followed by `…`.
  - `who` is the same as in `render.segment_line`: `speaker_name`, else
    `speaker_label`, else `?`.

## Current state

`transcriber_cli/suspects.py` is pure functions over the API's dicts.
`SENTENCE_END = re.compile(r"[.!?…]+")` already exists there.
`repetition_windows(segments)`, `low_confidence_passages(words, segments,
below)` and `corrected_segments(segments)` are each tested in
`tests/test_cli_suspects.py`, with the helper
`seg(order, start, end, text, **kw)`.

`transcriber_cli/main.py:220`, `cmd_suspects(api, args)`, builds the sections:

```python
    lines = []
    for title, entries in (
        ("REPEATED (possible hallucination over silence)", [...]),
        ("LOW-CONFIDENCE PASSAGES (worst first)", [passage_entry(p) for p in passages]),
        ("CORRECTED BY VOCABULARY", fixes),
    ):
        lines += _section(title, entries, args.limit)
    emit(args, {
        "repeated": windows,
        "low_confidence_passages": passages,
        "corrected_segments": corrected,
    }, lines)
```

`render.py` has `clock(seconds)` and `segment_line(seg)`. The keys of a
Segment dict are those of `models/segment.py:to_dict`: `order`,
`start_time`, `end_time`, `text`, `speaker_id`, `speaker_label`,
`speaker_name`, `is_edited`, `speaker_edited`, `confidence`, `corrections`.

The end-to-end CLI tests are in `tests/test_transcriber_cli.py`, for example
`test_suspects_lists_vocabulary_corrections`. They use `seed_meeting`,
`add_speaker` and `add_segment(db, meeting, speaker, order, start, end, text, **kw)`.

The operator skill, `.claude/skills/transcriber-operator/SKILL.md`, phase 4
"Review", says "`suspects M` prints up to three sections" and has a table
with one row per section. The skill's Done line for phase 4 is: "every
`suspects` entry is fixed, left as a Review Note, or (a REPEATED range)
reported to the user."

## Steps

Call the `tdd` skill first. The agreed seams are
`transcriber_cli.suspects.speaker_cuts` (pure) and the `suspects` command
output through the existing CLI test harness. Each test goes red first.

1. **Pure rule.** In `tests/test_cli_suspects.py`, write one test at a time:
   - two Segments of different Speakers 0.3 s apart, where the first is
     `"É, tá"`, give one entry
     `{"first_order": …, "second_order": …, "gap": 0.3}`;
   - the first Segment ends with `"."`, `"?"`, `"!"` or `"…"` (parametrize):
     no entry;
   - the same Speaker on both sides: no entry;
   - a gap of 1.5 s: no entry. A gap of exactly 1.0 s gives an entry;
   - either Segment has `speaker_edited=True`: no entry;
   - Segments passed out of order are handled by `order`;
   - a Segment without a `speaker_id` (None) on either side: no entry.

   Implement `speaker_cuts(segments, max_gap=CUT_MAX_GAP)` in
   `transcriber_cli/suspects.py`, with a docstring that says what the pair
   means: a sentence that continues across a change of Speaker, usually a
   Diarizer boundary shifted by a few Words.
   Verify: `uv run --extra dev pytest -q tests/test_cli_suspects.py`.
2. **Command output.** In `tests/test_transcriber_cli.py`, add
   `test_suspects_lists_sentences_cut_by_a_speaker_change`. Seed two
   Speakers and the Segments `#68` (Abner, 151.0 to 151.6, "É, tá") and `#69`
   (Garrah, 151.7 to 153.0, "errado aqui, capitão."). Assert:
   - the heading `SENTENCE CUT BY A SPEAKER CHANGE` appears;
   - the exact line
     `  #68 02:31 Abner: "É, tá" | #69 Garrah: "errado aqui, capitão."` appears.
     Adapt it only if `clock(151.0)` renders differently; check
     `render.clock` first;
   - under `--json`, `"speaker_cuts"` holds the one entry.

   Add a second test for truncation: a first text of 80 characters shows
   `"…` plus its last 60. Then wire the section into `cmd_suspects`, the
   `emit` dict, and the `_section` loop.
   Verify: `uv run --extra dev pytest -q tests/test_transcriber_cli.py -k suspects`.
3. **Skill.** Before editing `SKILL.md`, invoke the `writing-for-agents`
   skill and let it govern the edit. In phase 4:
   - "up to three sections" becomes "up to four sections";
   - add a table row:
     `| SENTENCE CUT BY A SPEAKER CHANGE | A sentence that continues across two Speakers: the Diarizer usually moved the boundary by a few Words. Read the pair in context (show --from --to). If the text proves who finishes or starts the sentence, assign the short side to that Speaker; when the cut falls inside a line, split it. Otherwise suggest-move. A real interruption stays as it is. |`;
   - the Done line also accepts "judged a real interruption".

   Keep the wording consistent with the skill's existing terms (Segment,
   Speaker, `assign`, `split`, `suggest-move`).
4. **README.** At `README.md` around line 139, the CLI examples include
   `suspects <id>`. If the README describes the `suspects` sections in
   prose anywhere (`rg -n "LOW-CONFIDENCE|REPEATED|suspects" README.md`),
   add the new section in the same style. If it only lists the command,
   change nothing.
5. **Gates.** `uv run --extra dev pytest -q` from the root and `npm test` in
   `frontend/`. Both pass. Mark 039 DONE in `plans/README.md`.

## Hard boundaries

- In scope: `transcriber_cli/suspects.py`, `transcriber_cli/main.py`
  (`cmd_suspects` only), `tests/test_cli_suspects.py`,
  `tests/test_transcriber_cli.py`, `.claude/skills/transcriber-operator/SKILL.md`,
  `README.md` (step 4 only), `plans/README.md`.
- Out of scope: the app (`api/`, `transcript/`, `tasks/`), the frontend, and
  any Segment derivation change.
- Never touch `storage/`, the real database, `models/` or `.env`. Never run
  the CLI against the live app; the tests use their own harness.
- Every file change goes through the Edit and Write tools.

## STOP conditions

- The drift check prints changes to an in-scope file.
- The `suspects` command's output structure differs from the excerpt above
  (for example, the sections are no longer built in one loop).
- `writing-for-agents` is not available.

## Done criteria

- `uv run --extra dev pytest -q`: all pass.
- `cd frontend && npm test`: all pass.
- `rg -n "SENTENCE CUT BY A SPEAKER CHANGE" transcriber_cli .claude/skills/transcriber-operator/SKILL.md`:
  a hit in each.

## Maintenance note

The rule depends on the Transcriber punctuating. A Preset without
punctuation (some Whisper settings) never ends a Segment with a sentence
end, so every handoff within 1 s would be listed. If that shows up, gate the
section on the Meeting having any sentence-final punctuation at all.
Segment derivation's break rules (`transcript/segments.py:_breaks_before`)
are what make the signal meaningful; a change there must revisit this rule.
