# Plan 030: The CLI edits Meetings, lists suspect passages, and ships an operator skill

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report; do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat c5cc40a..HEAD -- transcriber_cli/ api/segments.py api/speakers.py api/speaker_profiles.py api/meetings.py .gitignore AGENTS.md`
> Plans 025–029 are expected to have changed these. Confirm the routes in
> "Current state" exist in the live code; if one is missing, STOP.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW
- **Depends on**: plans 025, 026, 027, 028, 029 (027 and 028 only for the
  behavior the skill promises: live refresh and names that survive Reprocessing)
- **Category**: direction, docs
- **Planned at**: commit `c5cc40a`, 2026-10-09
- **Source**: agent-friendliness audit, 2026-10-09. User decisions: agent text
  edits do not teach Vocabulary unless the user confirms (`--learn`); renaming
  creates a Voice Profile only when asked (`--save-profile`).

## Why this matters

The user's goal: an agent mediates the transcription in the coding session,
names the Speakers the Diarizer and Voice Profiles could not, judges
transcription errors, and fixes Segments while the Meeting page updates live.
Plan 029 gave the agent eyes. This plan gives it hands (edit commands), a
starting point for review (`suspects`), and the procedure (a skill), so any
session can run the workflow the same way without rediscovering the API.

## Current state

Routes (after plans 025–028), all under `/api`:

| Route | Body / notes |
|---|---|
| `PUT /speakers/{id}` | `{"display_name": str}` → sets `identified_by="manual"` |
| `POST /speakers/merge` | `{"source_id", "target_id"}` (same Meeting) |
| `POST /meetings/{id}/speakers` | `{"display_name": str}` → new `MANUAL_n` Speaker |
| `PUT /segments/{id}` | `{"text": str, "learn": bool}` (`learn` defaults to true server-side; the CLI always sends it) |
| `PUT /segments/{id}/speaker` | `{"speaker_id": str}` |
| `POST /segments/{id}/revert` | restores `original_text`; 409 when not edited |
| `PUT /meetings/{id}` | `{"title"?, "vocabulary"?, "participants"?}` |
| `POST /speaker-profiles/save-from-speaker` | `{"speaker_id", "meeting_id", "name"?}` → creates or updates a Voice Profile from that Speaker's audio |
| `GET /meetings/{id}/words` | Words as heard, with `confidence` (plan 026) |

Every mutating route returns 409 while the Meeting is PROCESSING (plan 025)
and publishes `{"type": "meeting_changed"}` so an open Meeting page refetches
(plan 027).

`transcriber_cli/` (plan 029) provides `Api`, `ApiError`, `resolve_meeting`,
`resolve_segment`, `resolve_speaker`, `render.segment_line`, `render.clock`,
`render.parse_clock`, `main(argv=None, api=None)`, and a test transport over
`TestClient` in `tests/test_transcriber_cli.py`.

Other facts:
- `.gitignore` line 53 ignores `.claude/` entirely, so a skill under
  `.claude/skills/` is not committed today.
- The user has a personal skill `ata-de-reuniao` (outside this repo) that
  turns an exported transcript JSON into meeting minutes. Its triage names
  four failure modes. The two this plan can detect mechanically are
  **silence hallucination** ("the same phrase in dozens of consecutive
  segments") and **low-confidence words**. Contamination (a side conversation)
  and shared errors need a reader. The skill text below tells the agent to
  look for them.
- ADR-0010 (plan 024) is the decision this skill operates under.
- Glossary: **Speaker Namer** "assigns a name to each Speaker — by matching a
  Voice Profile, or by falling back to 'Participant N'". **Voice Profile** is
  about a real person across Meetings, and **Speaker** exists only inside one Meeting.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| CLI tests | `uv run pytest -q tests/test_transcriber_cli.py tests/test_cli_suspects.py` | all pass |
| Backend gate | `uv run pytest -q` | 0 failures |
| Frontend gate | `npm test` in `frontend/` | all pass |
| Ignore check | `git check-ignore -v .claude/skills/transcriber-operator/SKILL.md` | no output, exit 1 (not ignored) |

## Suggested executor toolkit

- **Before writing `SKILL.md`, invoke the `writing-for-agents` skill** (the
  user's global rule for any skill file) and let it govern the wording. The
  content outline in Step 4 is the substance, and that skill decides the form.
- Call the Skill tool with `tdd` for `suspects.py`.

## Scope

**In scope**:
- `transcriber_cli/main.py`, `transcriber_cli/suspects.py` (create)
- `tests/test_transcriber_cli.py`, `tests/test_cli_suspects.py` (create)
- `.gitignore` (un-ignore only `.claude/skills/transcriber-operator/`)
- `.claude/skills/transcriber-operator/SKILL.md` (create)
- `AGENTS.md` (one short section)

**Out of scope**: the app (`api/`, `models/`, …). Do not commit any other
`.claude/` content: `settings.local.json`, `agents/` and `skills/impeccable/`
stay ignored.

## Git workflow

- Branch: `advisor/030-cli-edits-skill`; commits like
  `feat(cli): rename, edit, revert and assign from the command line`,
  `feat(cli): list suspect passages`, `docs(skills): a transcriber operator skill`.
- Do not push.

## Steps

### Step 1: Edit commands

Add to `main.py`. Every command resolves handles with plan 029's helpers,
fetches the Meeting once (`GET /api/meetings/{id}`), and prints the updated
object as a Segment or Speaker line.

| Command | Calls |
|---|---|
| `rename M SPEAKER NAME [--save-profile]` | `PUT /speakers/{id}`. With `--save-profile`, then `POST /speaker-profiles/save-from-speaker` with `name=NAME` and prints `voice profile saved: NAME` |
| `add-speaker M NAME` | `POST /meetings/{id}/speakers` |
| `merge M SOURCE TARGET` | `POST /speakers/merge` |
| `edit M SEG TEXT [--learn]` | `PUT /segments/{id}` with `{"text": TEXT, "learn": <flag>}` |
| `revert M SEG` | `POST /segments/{id}/revert` |
| `assign M SEG SPEAKER` | `PUT /segments/{id}/speaker`. `SPEAKER` of the form `new:Nome` first runs `add-speaker` and uses the new id |
| `set M [--title T] [--participants S] [--vocabulary S]` | `PUT /meetings/{id}` with the given fields only |

**Verify**: CLI tests 1–6 in the Test plan pass.

### Step 2: `suspects.py` (pure)

```python
"""Passages of a Meeting worth a second look, found without hearing the audio."""

def repetition_windows(segments: list[dict], min_run: int = 3) -> list[dict]:
    """Runs of the same sentence repeated back to back: the signature of a
    Transcriber filling silence. Returns {start, end, first_order, last_order, text, count}."""

def low_confidence_words(words: list[dict], segments: list[dict], below: float = 0.6) -> list[dict]:
    """Words under ``below``, each tagged with the order of the Segment whose time contains it."""

def corrected_segments(segments: list[dict]) -> list[dict]:
    """Segments where Vocabulary Correction replaced a heard form."""
```

Sentence rule for `repetition_windows`: split each Segment's text on
`[.!?…]+`, normalize each sentence (casefold, keep letters and digits,
collapse whitespace), drop empty ones, and walk the flat sequence in Segment
order. A run is `min_run` or more consecutive equal sentences, within one
Segment or across neighbors. `start`/`end` come from the first and last
Segments the run touches.

**Verify**: `uv run pytest -q tests/test_cli_suspects.py` (cases in the Test plan).

### Step 3: `suspects` command

`suspects M [--below 0.6] [--limit 40]` prints up to four sections, skipping
empty ones. Each section has a heading line, then entries:

```
REPEATED (possible hallucination over silence)
  12:03-14:40 #210-#236 x27 "obrigado"
LOW-CONFIDENCE WORDS
  #142 03:41 Galo (0.31) | #142 03:41 Maria: ... Galo confirmou ...
CORRECTED BY VOCABULARY
  #77 01:12 Galo->Garrah (rule similar)
LOW-CONFIDENCE SEGMENTS
  <segment_line for each Segment with confidence < below>
```

It fetches the Meeting once and the Words once (`GET .../words`). `--limit`
caps each section, and the heading then says `(showing N of M)`.

**Verify**: CLI test 7 passes.

### Step 4: Operator skill

1. `.gitignore`: replace the line `.claude/` with:

   ```
   .claude/*
   !.claude/skills/
   .claude/skills/*
   !.claude/skills/transcriber-operator/
   ```

   **Verify**: `git check-ignore -v .claude/skills/transcriber-operator/SKILL.md`
   → exit 1; `git check-ignore -v .claude/settings.local.json` → still ignored;
   `git status --short .claude` → only the new skill.

2. Invoke `writing-for-agents`, then write
   `.claude/skills/transcriber-operator/SKILL.md`. Frontmatter: `name:
   transcriber-operator`, plus a `description` that triggers on transcribing a
   recording with this app, naming Speakers in a Meeting, reviewing or
   correcting a Meeting's transcript, and "transcrever / revisar transcrição /
   nomear falantes". The body must carry this substance:

   - **Preflight.** `uv run python -m transcriber_cli health`. Exit 2 means
     the app is down. Start it in the background with `./start.ps1`
     (Windows) or `./start.sh`, and wait for `health` to succeed.
   - **Privacy.** ADR-0010: the agent reads transcript text, and a hosted
     model takes it off the machine. Say so once when the user has not
     already chosen this. Never paste audio paths or transcripts into web
     tools.
   - **Transcribe.** `upload FILE --title ... --participants "A, B" --vocabulary "..." --process --wait`.
     Ask for participants and domain terms first; they are the best evidence
     for naming and correcting.
   - **Name Speakers.** `speakers M --unnamed` shows only those no Voice
     Profile matched, with sample lines. Evidence, strongest first:
     self-introduction, being addressed by name followed by that Speaker
     answering, the participants list combined with role and topic. A name
     needs evidence quoted with Segment handles. Without it, ask the user
     with the samples and timestamps; never guess. `rename`. Offer
     `--save-profile` only after the user confirms the name, and say it makes
     future Meetings name that voice automatically. When one label holds two
     people, use `add-speaker` and `assign`, and tell the user which
     Segments moved.
   - **Review.** `suspects M`, then `show M --from --to` around each hit.
     Fix only what the transcript itself supports: a term in the vocabulary or
     participants, the same word spelled right elsewhere, an obvious grammar
     mishearing in context. Use `edit` without `--learn`. Repetition windows
     over silence are not text to fix: report the time range. List
     everything uncertain as `#N clock "heard" -> "maybe"` for the user to
     re-listen. Look by reading for the two failure modes no command finds:
     a side conversation captured by an open mic (a long block from someone
     who barely speaks otherwise, off-topic) and plausible-sounding numbers.
   - **Live.** Every change appears on the open Meeting page without a
     reload. Tell the user they can watch it there.
   - **Learning.** Use `--learn` only on corrections the user confirmed. A
     learned Misheard Form applies to every future Meeting.
   - **Undo.** `revert M #N`. Names and reassignments survive Re-identify and
     Reapply Vocabulary. Re-diarize carries names by Turn overlap and drops
     reassignments, so warn before suggesting it.
   - **Minutes.** For a meeting record, export JSON
     (`export M --format json --out ...`) and hand it to the user's
     minutes workflow if one exists. This skill stops at a reviewed transcript.
   - **Command reference.** One line per command, from `--help`.

   Keep the file under ~150 lines. Link to `docs/adr/0010-...` and
   `GLOSSARY.md` rather than restating them.

### Step 5: AGENTS.md pointer

Add a section to `AGENTS.md`:

```markdown
## Operating the app

To transcribe, name Speakers, or correct a Meeting (rather than change the code),
follow `.claude/skills/transcriber-operator/SKILL.md`; it drives the running app
through `uv run python -m transcriber_cli`. ADR-0010 says why that is allowed.
```

**Verify**: `rg -n "transcriber-operator" AGENTS.md` → one match.

## Test plan

`tests/test_transcriber_cli.py` (extend, same transport and `db_session`):

1. `rename` sets `display_name` and `identified_by == "manual"`.
2. `rename --save-profile` calls save-from-speaker. Monkeypatch the route's
   embedding work: patch `api.speaker_profiles.EmbeddingService.extract_embedding`
   to return a numpy vector and `subprocess.run` in that module to succeed, or
   assert the CLI sends the right request through a recording transport. Pick
   the second if the first needs audio files.
3. `edit` sends `learn: false` by default (no new `VocabularyEntry`), and
   `--learn` teaches (a `misheard_as` entry appears, as in
   `test_segment_edits_learn_and_increment_misheard_form`).
4. `revert` restores the text, and `revert` on an unedited Segment exits 1 with the server message.
5. `assign #N new:Carla` creates `MANUAL_1` "Carla" and moves the Segment.
6. `set --participants "Ana, Bruno"` updates only participants.
7. `suspects` prints the REPEATED and LOW-CONFIDENCE WORDS headings for a seeded
   Meeting with 3 consecutive "Obrigado." Segments and one Word at 0.3.

`tests/test_cli_suspects.py` (pure):

1. Three Segments "Obrigado." → one window, count 3, first/last order correct.
2. "Obrigado. Obrigado. Obrigado." inside one Segment → one window.
3. Two repeats → no window (`min_run=3`).
4. Case and punctuation differences still match ("obrigado!" / "Obrigado.").
5. `low_confidence_words` tags the containing Segment's order and skips
   `confidence=None`.
6. `corrected_segments` returns only Segments with non-empty `corrections`.

## Done criteria

- [ ] `uv run pytest -q` exits 0 with the new tests; `npm test` exits 0
- [ ] `git check-ignore .claude/skills/transcriber-operator/SKILL.md` exits 1; `git check-ignore .claude/settings.local.json` exits 0
- [ ] `SKILL.md` exists, has `name: transcriber-operator`, and mentions `--learn`, `--save-profile`, `suspects` and `revert`
- [ ] `rg -n "transcriber-operator" AGENTS.md` → one match
- [ ] Manual (record "not run" if no app/GPU): on a real Meeting, `speakers --unnamed`, `rename`, `edit` and `suspects` run and the open page updates live
- [ ] `plans/README.md` row for 030 updated

## STOP conditions

- Any route in "Current state" is missing or rejects the body shown.
- The `.gitignore` change would also un-ignore `settings.local.json` or other
  `.claude/` files (check with `git status --short .claude`).
- The `writing-for-agents` skill is unavailable and cannot be installed
  (`npx skills@latest add mattpocock/skills`). Write the skill anyway from the
  outline, and record that in the outcome note.

## Maintenance notes

- The skill and the CLI's output markers form one interface. Change them together.
- If the Speaker Namer ever gets an in-app intro-reading namer (ADR-0002's
  reserved slot), the skill's naming section shrinks to reviewing its output.
- `suspects` heuristics are deliberately simple. Add new ones only with a
  failing example from a real Meeting.
