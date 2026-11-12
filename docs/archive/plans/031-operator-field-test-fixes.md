# Plan 031: Fixes from the first real operator session

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report; do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat deb4da8..HEAD -- transcriber_cli/ transcript/vocabulary_correction.py tasks/vocabulary.py .claude/skills/transcriber-operator/SKILL.md README.md`
> Any output is a STOP condition until you have compared it against the excerpts below.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW (CLI and one Vocabulary learning fix; no schema change)
- **Depends on**: 029, 030 (DONE)
- **Category**: bug + DX
- **Planned at**: commit `deb4da8`, 2026-10-09
- **Source**: the first real use of the `transcriber-operator` skill on
  2026-10-09: a new dual-track Meeting (2026-10-01 Brasil Urbano) was
  transcribed and named, and an old one (2026-10-01 Sinop) was reviewed. The
  user corrected several of the agent's calls. Each item below is something
  that went wrong or cost time in that session.

## Why this matters

ADR-0010 lets a coding agent operate the app through `transcriber_cli`. In
the first real session:

1. The `upload --process --wait` progress never appeared. stdout is
   block-buffered when it is a pipe, and a pipe is exactly how an agent runs
   the CLI. The whole log arrived only when the process exited.
2. `speakers --unnamed` hid the dual-track HOST, whose default name is "You".
   The agent had to notice it on its own.
3. `suspects` listed 936 and 645 "low-confidence Words" for 36- and 26-minute
   Meetings. Each Word got its own line, which repeated the whole Segment. The
   real problems (a 0.14 Word inside a misheard place name) were buried.
4. `show --from/--to` printed the full Meeting header on every call. That
   header includes ~1.5 kB of vocabulary and the Speaker list, and the agent
   called the command over and over to read short passages.
5. Finding a passage by text (a name, a number) needed a dump to a file and
   `rg`. The CLI had no text filter.
6. **App bug**: the first edit that teaches a *new* term loses its Misheard
   Form. `learn_from_edit` adds the new `VocabularyEntry` and then looks it up
   to attach the form. The session runs with autoflush off, so the lookup
   misses the new row and the form is dropped. In the session, `Informakon`
   and `Pacaembu` were learned with `misheard_as == []`, and `DWG` lost its
   first form.
7. Learned forms keep edge punctuation from the transcript (`"BWG,"`,
   `"de WG,"`). Matching normalizes them away, but the Vocabulary settings
   page shows them as typed.
8. The skill's naming rules were too trusting. The user corrected the agent
   in three places:
   - A name heard once ("Luiz") was itself misheard. The Speaker was Lourdes,
     a regular with a Voice Profile.
   - Small Speakers (4 Segments) are usually the Diarizer splitting a person.
     They are not a new attendee.
   - A loudspeaker announcement captured by the mic needs its own Speaker.

## Current state

- `transcriber_cli/__main__.py`:

  ```python
  # Piped output (an agent reading stdout) is UTF-8 whatever the Windows code page says.
  for stream in (sys.stdout, sys.stderr):
      stream.reconfigure(encoding="utf-8", errors="replace")
  ```
- `transcriber_cli/main.py`:
  - `_wait` prints progress lines with plain `print(...)`.
  - `_is_unnamed`:

    ```python
    def _is_unnamed(speaker):
        return speaker.get("identified_by") is None and speaker["label"] != "UNKNOWN"
    ```

    The dual-track HOST is created with `identified_by == "host_track"` and
    the name "You". Values in use: `None`, `"voice_profile"`, `"manual"`,
    `"host_track"`.
  - `cmd_show` always builds `lines = meeting_header(meeting)` plus the
    Speaker lines, then the Segment lines. It filters by `--speaker`,
    `--from`/`--to` (`_overlaps`) and `--limit`.
  - `cmd_suspects` builds four sections with `_section(title, entries, limit)`:
    - `REPEATED`;
    - `LOW-CONFIDENCE WORDS`: one entry per Word under `--below`, whose
      default is `render.LOW_CONFIDENCE = 0.6`, each followed by
      `| <segment_line>`;
    - `CORRECTED BY VOCABULARY`;
    - `LOW-CONFIDENCE SEGMENTS`: Segment confidence under `--below`.
- `transcriber_cli/suspects.py`: `repetition_windows`, `low_confidence_words`
  (tags each Word with `segment_order`), `corrected_segments`.
- `tasks/vocabulary.py` `learn_from_edit`:

  ```python
  for term in dict.fromkeys(terms):
      existing = db.query(VocabularyEntry).filter(VocabularyEntry.term == term).first()
      if existing:
          existing.frequency += 1
      else:
          db.add(VocabularyEntry(term=term, source_meeting_id=meeting_id))

  for heard, term in forms:
      _record_misheard_form(db, heard=heard, term=term)   # queries db.query(VocabularyEntry).all()
  ```
- `transcript/vocabulary_correction.py` `learned_from_edit(before, after, ...)`
  diffs `before.split()` with `after.split()` (SequenceMatcher). It returns
  the replaced or inserted phrases as terms and `(old_phrase, new_phrase)` as
  forms. Words keep their punctuation, e.g. `"BWG,"`. Its tests live in
  `tests/test_vocabulary_correction.py`. Check this with `rg -n "learned_from_edit" tests/`.
- Tests:
  - `tests/test_meeting_api.py::test_segment_edits_learn_and_increment_misheard_form`
    always creates the `VocabularyEntry` *before* editing, so the new-term
    path has no test.
  - CLI tests are in `tests/test_transcriber_cli.py` and
    `tests/test_cli_suspects.py`. They use the TestClient transport and the
    `db_session` fixture from `tests/conftest.py`.
- `.claude/skills/transcriber-operator/SKILL.md`, phases 3 (Name Speakers) and
  4 (Review), plus a "Line markers" section.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Focus | `uv run pytest -q tests/test_transcriber_cli.py tests/test_cli_suspects.py tests/test_meeting_api.py tests/test_vocabulary_correction.py` | all pass |
| Gate | `uv run pytest -q` (repo root) | 0 failures |
| Frontend gate | `npm test` in `frontend/` | all pass |

## Scope

**In scope**:
- `transcriber_cli/__main__.py`, `transcriber_cli/main.py`, `transcriber_cli/suspects.py`
- `tasks/vocabulary.py` (`learn_from_edit`)
- `transcript/vocabulary_correction.py` (`learned_from_edit`, edge punctuation only)
- `tests/test_transcriber_cli.py`, `tests/test_cli_suspects.py`, `tests/test_meeting_api.py`,
  `tests/test_vocabulary_correction.py` (or wherever `learned_from_edit` is tested)
- `.claude/skills/transcriber-operator/SKILL.md`
- `README.md` ("Command line" section only)

**Out of scope**:
- The Diarizer and its parameters.
- Splitting a Segment. That is a separate design item; see `plans/README.md`.
- The frontend.
- Existing stored Misheard Forms. Do not migrate or clean the user's data.

## Git workflow

- Branch `advisor/031-operator-field-test`. One commit per step, e.g.
  `fix(cli): progress reaches a piped stdout`.
- Do not push.

## Steps

Test first for every step: the new test fails before the change. Show the red run.

### Step 1: Line-buffered output

In `transcriber_cli/__main__.py`, change the reconfigure call to
`stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)`
and extend the comment ("...and each line reaches it as it is printed").

**Verify**: new test `test_piped_stdout_is_line_buffered`. In a subprocess,
with stdout piped (`subprocess.run([sys.executable, "-c", CODE], capture_output=True)`),
run code that executes `transcriber_cli/__main__.py`'s reconfigure the same
way the module does and prints `sys.stdout.line_buffering`. Expect `True`.
If running the module's top level is awkward because it calls `main()`, move
the reconfigure loop into a small function `_configure_streams()` in
`__main__.py`, call it from the module, and test that function directly on
an `io.TextIOWrapper` over a `BytesIO`. The test must fail before the change.

### Step 2: `--unnamed` includes default names

Change `_is_unnamed` so a Speaker is unnamed when `identified_by` is
`None` **or** `"host_track"`, and its label is not `UNKNOWN`. Add a
docstring: "No Voice Profile matched it and no person named it; the
dual-track HOST starts as 'You'."

**Verify**: new test `test_speakers_unnamed_lists_a_default_host`. Use a
Meeting with a HOST Speaker (`label="HOST"`, `display_name="You"`,
`identified_by="host_track"`), one `voice_profile` Speaker and one `manual`
Speaker. `speakers M --unnamed` lists only HOST.

### Step 3: `show` prints the header only for a whole-Meeting read

In `cmd_show`, prepend the header and Speaker lines only when no filter is
given: no `--speaker`, `--from`, `--to`, `--grep` and no `--limit`. With any
filter, print only the Segment lines. `--json` output is unchanged.

Add `--grep PATTERN`: a case-insensitive regular expression matched against
each Segment's `text`. It combines with the other filters. Report an invalid
pattern as an `ApiError(400, "invalid --grep pattern: ...")`, so it exits 1
like the other user errors. Check the existing exit-code mapping in `main()`
and match it.

**Verify**: new tests:
- `test_show_range_prints_only_segments`: no `vocabulary:` and no Speaker
  line appear when `--from`/`--to` is used.
- `test_show_grep_filters_segments`: matches with any letter case, and
  combines with `--speaker`.
- `test_show_without_filters_keeps_header`.

### Step 4: `suspects` groups weak Words by Segment, worst first

In `transcriber_cli/suspects.py`, add:

```python
def low_confidence_passages(words, segments, below=0.4) -> list[dict]:
    """Segments holding at least one Word under ``below``, worst Word first.
    Returns {order, worst, words: [(text, confidence), ...]} sorted by worst ascending."""
```

Word-to-Segment ownership follows `low_confidence_words`:
`start_time <= word.start < end_time`. Words outside every Segment are
dropped. Delete `low_confidence_words` if nothing else uses it; check with
`rg -n low_confidence_words`. Replace its tests.

In `cmd_suspects`:
- Replace the `LOW-CONFIDENCE WORDS` and `LOW-CONFIDENCE SEGMENTS` sections
  with one section, `LOW-CONFIDENCE PASSAGES (worst first)`. Each entry is
  `segment_line(seg) + " | weak: algo 0.14, Do 0.37"`, with the weak Words in
  time order.
- `--below` now means the Word threshold, with default `0.4`. Name the
  constant `WEAK_WORD = 0.4` in `suspects.py`, with a comment that Segment
  confidence (0.6, `render.LOW_CONFIDENCE`) is a different scale.
- Keep `--limit`, `REPEATED` and `CORRECTED BY VOCABULARY` unchanged.

**Verify**: new tests:
- `low_confidence_passages` groups two weak Words of one Segment into one
  entry, sorts by worst, and skips strong Segments.
- The CLI test asserts one line per Segment and the `weak:` list.
- Update any test that asserted the old section titles.

### Step 5: A new term keeps its first Misheard Form

In `tasks/vocabulary.py` `learn_from_edit`, call `db.flush()` after the term
loop and before recording forms, with the comment "so a term added above is
found when its Misheard Form is recorded".

**Verify**: new test in `tests/test_meeting_api.py`,
`test_an_edit_teaching_a_new_term_records_its_misheard_form`. Start with no
`VocabularyEntry` and a Segment whose text is `"Quem mandou o Infarmacom"`.
`PUT /api/segments/{id}` with `{"text": "Quem mandou o Informakon"}`
(`learn` defaults to true). Then
`VocabularyEntry.term == "Informakon"` exists with
`misheard_as == [{"form": "Infarmacom", "count": 1}]`. It must fail before
the flush.

### Step 6: Learned phrases lose edge punctuation

In `learned_from_edit`, strip leading and trailing punctuation from each
phrase with `.strip(EDGE_PUNCTUATION)`. Define
`EDGE_PUNCTUATION = ".,;:!?…\"'()[]"` near the other constants. Apply it to
`new_phrase` (the term) and `old_phrase` (the form) before
`_worth_learning`/the pair. Internal punctuation stays (`Habite-se`, `8,3%`).

**Verify**: new unit test: `learned_from_edit("o BWG, com", "o DWG, com")`
returns forms `[("BWG", "DWG")]` and terms `["DWG"]`. All existing
`learned_from_edit` tests pass unchanged. If one fails because it expected
punctuation, STOP and report.

### Step 7: Skill update

**Invoke the `writing-for-agents` skill before editing `SKILL.md`** (the
user's global rule) and let it govern the edit. Keep the file's phase
structure. Add these rules:

- **Phase 3, before naming:**
  - A small Speaker (a handful of Segments, seconds of speech) is usually the
    Diarizer splitting a person, not a new attendee. Read the Segments before
    and after it. If it alternates with one Speaker within seconds, or its
    lines continue that Speaker's sentence, `merge` it into that Speaker and
    say so.
  - The reverse also happens: one Speaker can hold two people, so the same
    before/after reading applies when a Speaker's lines answer each other.
- **Phase 3, evidence:**
  - A name heard once may itself be a mishearing. Before applying it, compare
    it with the regular attendees: Voice Profile names, the Speakers of the
    user's other Meetings with the same title pattern (`list`, then
    `speakers`), and the participants list. A near-sound regular ("Luiz" /
    Lourdes) wins over a new name.
  - In a recurring meeting, ask the user before naming someone new.
- **Phase 3, HOST:** the dual-track HOST is the user (the mic owner). Rename
  "You" to the user's name. `--unnamed` now lists it.
- **Phase 3, background audio:** a loudspeaker, a TV or another room picked
  up by a mic goes to its own Speaker with `assign M #N new:"Alto-falante"`.
  Do not attribute it to a participant and do not correct its text.
- **Phase 4:**
  - Use `show M --grep PATTERN` to find names, numbers and terms.
  - `suspects` now prints `LOW-CONFIDENCE PASSAGES`. Update the section table.
  - Report implausible numbers to the user and never correct a number
    yourself.
- **Learning:** to teach a new term, first edit with `--learn` changing only
  the misheard words, then fix the rest of the sentence in a second `edit`
  without `--learn`. A whole-sentence rewrite teaches nothing, because only
  short replaced phrases are learned.

**Verify**: `rg -n "grep|Alto-falante|merge|HOST|LOW-CONFIDENCE PASSAGES" .claude/skills/transcriber-operator/SKILL.md`
shows each rule. Keep the file under ~110 lines.

### Step 8: README and gate

Add one `show M --grep "Lourdes"` example line to README's "Command line"
section.

**Verify**: `uv run pytest -q` exits 0, and `npm test` in `frontend/` passes.

## Done criteria

- [ ] `uv run pytest -q` exits 0; the new tests from Steps 1–6 exist and were red first
- [ ] `rg -n "line_buffering=True" transcriber_cli/__main__.py` matches
- [ ] `rg -n "LOW-CONFIDENCE WORDS|LOW-CONFIDENCE SEGMENTS" transcriber_cli/` has no match
- [ ] `rg -n "db.flush" tasks/vocabulary.py` matches inside `learn_from_edit`
- [ ] SKILL.md carries the Step 7 rules, written after invoking `writing-for-agents`
- [ ] `plans/README.md` row for 031 updated

## STOP conditions

- The drift check shows changes not described here.
- `line_buffering=True` breaks the UTF-8 reconfigure on this Python version.
  Report the traceback.
- An existing `learned_from_edit` test expects punctuation in a form.
- `writing-for-agents` is unavailable.

## Maintenance notes

- `WEAK_WORD` (0.4, Word confidence) and `LOW_CONFIDENCE` (0.6, Segment
  confidence) are different scales. Do not unify them without checking what
  the Transcriber emits.
- Existing stored forms with punctuation stay as they are. The user can
  delete them on the Vocabulary page.
