# Plan 036: The split as a Review Note suggestion

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report; do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**: confirm plan 035 is DONE in `plans/README.md`
> and `api/segments.py` has `split_segment`. Then run
> `git diff --stat <035 merge commit>..HEAD -- api/review_notes.py transcriber_cli/main.py frontend/src/`.
> Any output is a STOP condition until compared with the excerpts below.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: 032, 033, 035
- **Category**: feature
- **Planned at**: commit `dd93f82` plus plan 035, 2026-10-09
- **Source**:
  - `.scratch/agent-operation/issues/01-review-notes.md` (decision 2: "Split
    becomes a further kind once 02 lands");
  - `02-split-segment.md`.

## Why this matters

The agent cannot hear the audio. When the text alone does not show where the
second person starts, the agent should not cut. It should propose the cut and
let the user accept it with one click on the Review tab, the same way it
proposes text and Speaker changes today.

## Decisions

- New kind `split`, authored by the agent only. A user note is a comment;
  that rule already exists.
- Payload:
  - `at`: a number, seconds;
  - `preview`: the first words of the second half, display only;
  - optionally `target_label` or `new_name` for the second half, the same
    fields `speaker_move` uses.
- Accepting runs plan 035's `split_segment`. With a target, the second half
  goes to it, and `new_name` creates the Speaker first, as `speaker_move`
  does.
- Actions on the page: Accept, Dismiss (like `speaker_move`).

## Current state

- `api/review_notes.py`:
  - `KINDS` and `SUGGESTION_KINDS` tuples;
  - `_validated_payload(db, meeting_id, req)` validates per kind;
    `speaker_move` checks `segment_for_range(...)` and then `target_label` or
    `new_name`;
  - `_apply(db, note, req)` resolves the Segment with
    `segment_for_range(db, note.meeting_id, note.start_time, note.end_time)`
    (409 if `None`) and calls the route functions directly, e.g.
    `update_segment_speaker(segment.id, UpdateSegmentSpeakerRequest(...), db)`;
  - `new_name` uses
    `add_speaker(note.meeting_id, AddSpeakerRequest(display_name=...), db)["id"]`.

  Tests are in `tests/test_review_notes.py`.
- Plan 035 added `split_segment(segment_id, SplitSegmentRequest(at, speaker_id), db)`
  in `api/segments.py`. It is 409 for an edited Segment or one with no Word
  boundary.
- CLI `transcriber_cli/main.py`:
  - `cmd_suggest_move` and `_leave_note(api, args, meeting, anchor, kind,
    body, payload)`;
  - the `suggest-move` parser takes `segment`, `speaker` and `--why`;
  - plan 035's `split` resolves `--before` to a Word start. Reuse that
    resolver; do not copy it.
- Frontend:
  - `frontend/src/types.ts`: `ReviewNoteKind` union, and
    `payload: Record<string, string> | null`;
  - `frontend/src/utils/reviewNotes.ts`: `noteActions` (switch on kind) and
    `noteSummary`. For example, `speaker_move` gives
    `` `→ ${p.target_label ?? `new: ${p.new_name}`}` ``;
  - `frontend/src/components/ReviewPanel.tsx`: `KIND_LABELS`, typed
    `Record<ReviewNote["kind"], string>`, so TypeScript forces the new
    entry;
  - tests in `frontend/src/utils/reviewNotes.test.ts`.

## Scope

**In scope**: the files listed above, plus docs:
- `README.md`, the CLI line;
- the operator skill;
- the GLOSSARY Review Note entry, only if it lists the kinds.

**Out of scope**: a free-hand split control on the page, and any change to
`split_segment`.

## Git workflow

Branch `advisor/036-split-note`. Commits:
- `feat(review-notes): split suggestion`;
- `feat(meeting-page): split notes`;
- `docs: suggest-split`.

Do not push.

## Steps

### Step 1: Backend kind (TDD)

Add `"split"` to `KINDS` and `SUGGESTION_KINDS`.

Validation:
- a Segment at the range;
- not `is_edited` (400 `"the Segment is edited; revert it first"`);
- `payload.at` is a number with `segment.start_time < at < segment.end_time`;
- `preview` is a non-empty string;
- an optional `target_label` must be a Speaker of the Meeting, and an
  optional `new_name` must be a non-empty string; not both.

Apply:
- resolve the Segment (409 if gone);
- resolve the target as `speaker_move` does (or none);
- call `split_segment(segment.id, SplitSegmentRequest(at=payload["at"], speaker_id=target_id), db)`.

Tests in `tests/test_review_notes.py`, red first:
- creating a split note with no target, and with a `target_label`;
- 400 for an `at` outside the Segment, for an edited Segment, and for
  `author="user"`;
- accepting splits the Segment, puts the second half on the target, and
  resolves the note `accepted`;
- accepting after the Segment was edited gives 409, and the note stays open.

**Verify**: `uv run pytest -q tests/test_review_notes.py` passes.

### Step 2: CLI `suggest-split`

`suggest-split M #N (--at T | --before WORDS) [--speaker S|new:NAME] --why REASON`:
- resolve `at` with the same resolver as `split`;
- `preview` is the second half's first five Words as heard, joined;
- leave the note with `_leave_note(..., "split", args.why, payload)`.

Test in `tests/test_transcriber_cli.py`: `suggest-split --before ... --speaker ...`
creates an open `split` note with the expected payload.

**Verify**: `uv run pytest -q tests/test_transcriber_cli.py` passes.

### Step 3: Frontend

- `types.ts`:
  - add `"split"` to `ReviewNoteKind`;
  - widen `payload` to `Record<string, string | number> | null`;
  - fix any compile error at the use sites by converting with `String(...)`,
    and change no behavior.
- `reviewNotes.ts`:
  - `noteActions` returns `["accept", "dismiss"]` for an open `split`;
  - `noteSummary` gives
    `` `split before "${p.preview}"` `` plus
    `` ` → ${p.target_label ?? `new: ${p.new_name}`}` `` when a target is set.
- `ReviewPanel.tsx`: `KIND_LABELS.split = "split"`.
- Tests in `reviewNotes.test.ts`, red first:
  - the actions for open and resolved split notes;
  - the summary with and without a target.

**Verify**: `cd frontend && npm test`, `npx tsc -b` and `npm run build` pass.

### Step 4: Docs and skill

- `README.md`: add `suggest-split` where the other `suggest-*` commands are
  listed.
- Skill: **invoke `writing-for-agents` first**. In the
  transcriber-operator skill, next to plan 035's split rule, add the
  fallback: when the text does not show where the second person starts,
  `suggest-split` instead of `split`. Add it to the Commands line.

**Verify**: `rg -n "suggest-split" README.md .claude/skills/transcriber-operator/SKILL.md` matches both.

### Step 5: Gate

**Verify**: `uv run pytest -q` and `cd frontend && npm test` pass.

## Done criteria

- [ ] New backend, CLI and frontend tests were red first and pass
- [ ] `uv run pytest -q`, `npm test`, `npx tsc -b`, `npm run build` pass
- [ ] `git diff --stat <035 merge>..HEAD -- api/segments.py` is empty
- [ ] `plans/README.md` row for 036 updated

## STOP conditions

- Plan 035 is not merged or `split_segment` has a different signature.
- Widening `payload` breaks more than a handful of use sites. List them.
