# Plan 042: Vocabulary Corrections on the Meeting page and in Settings

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report; do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**: confirm plan 041 is DONE in `plans/README.md`,
> and that `GET /api/vocabulary/rejected-forms` and
> `POST /api/segments/{id}/corrections/confirm|reject` exist (`rg -n "rejected-forms|corrections/confirm|corrections/reject" api/`).
> Then run `git diff --stat 78ef268..HEAD -- frontend/src/`; any output is a
> STOP condition until compared with the excerpts below.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW
- **Depends on**: 041
- **Category**: feature (UI)
- **Planned at**: commit `8713b75` plus plans 040 and 041, 2026-10-10
- **Source**: `.scratch/architecture-review/issues/08-correction-suggestions-ui.md`,
  decided with the user on 2026-10-10.

## Why this matters

Plan 041 stores where each Correction sits in a Segment's text, and adds
confirm, reject and the Rejected Forms list. This plan shows them:
- the corrected Word is marked in the transcript; hovering or focusing it
  shows what was heard, with confirm and undo;
- Settings lists the Rejected Forms, so the user can take one back.

The user chose this layout from a preview:

```
...falou com o [Garrah]~~ ontem
            ┌──────────────────────────┐
            │ ouvido: "Galo"           │
            │ [✓ confirmar] [↶ desfazer] │
            └──────────────────────────┘
```

## Decisions

- **Mark.** An unconfirmed Correction gets a dotted violet underline
  (`decoration-dotted decoration-violet-400/70`). A confirmed one gets a faint
  slate dotted underline, so it stays findable but quiet.
- **Popover.**
  - It opens on hover and on keyboard focus: the mark is a `<button>` with
    `type="button"`.
  - It shows `heard: "<heard>"`. Write UI copy in English, as the rest of
    the page is.
  - Two buttons: **Confirm**, shown only when unconfirmed, and **Undo**.
    Their `title`s explain the effect: "Teach this form: it will be
    corrected the same way in future Meetings" and "Put back what was heard
    and never correct this form to this term again".
  - It closes on mouse leave, `Escape`, or after an action.
- **Click handling.** Clicking a Segment's text starts editing it today
  (`onClick={() => startEdit(seg)}`). A click on a mark or inside the
  popover must not start an edit, so call `stopPropagation`.
- **Low confidence.** The whole-text wavy amber underline stays. The marks
  render inside it.
- **No offsets.** A Correction without `text_start`/`text_end` (old data) is
  not marked, and the text renders as today.
- **After an action** the WebSocket refresh (plan 027) updates the Segment.
  Do not patch local state optimistically. A failed request shows the API's
  `detail` the way the page's other failed actions do; copy the pattern
  from the split and note actions in `ReviewPanel.tsx` or the edit save in
  `TranscriptView.tsx`.
- **Settings.** Under "Learned vocabulary" in `PreferencesTab.tsx`, add a
  "Never corrected" block:
  - copy line: "Heard forms you undid. Vocabulary Correction leaves them as
    heard.";
  - one chip per Rejected Form, `heard ↛ term`, with an × that deletes it
    (same chip and × style as the Misheard Forms there);
  - hidden when the list is empty.

## Current state

- `frontend/src/components/TranscriptView.tsx` renders a Segment's text
  around line 198:

  ```tsx
  <p className={...} onClick={() => startEdit(seg)} title={...}>
    {seg.confidence != null && seg.confidence < 0.6 ? (
      <span className="underline decoration-amber-500/70 decoration-wavy underline-offset-2">
        {seg.text}
      </span>
    ) : (
      seg.text
    )}
    ...
  </p>
  ```
- `frontend/src/types.ts` defines the Segment type. Check how `corrections`
  is typed today: `rg -n "corrections" frontend/src/types.ts`.
- `frontend/src/api.ts` holds the API functions (`deleteMisheardForm`,
  `listVocabulary` and so on) and their patterns.
- `frontend/src/components/settings/PreferencesTab.tsx` shows the
  "Learned vocabulary" chips with Misheard Forms and × buttons. The
  form-state hook is `usePreferencesForm.ts`, which loads `learnedVocab` in
  `loadPreferences`.
- Tests are vitest, colocated as `*.test.ts(x)`
  (`rg --files frontend/src | rg "\.test\."`). Pure helpers are tested
  directly. Follow `reviewNotes.ts` and its test from plan 036 for a pure
  helper next to a component.

## Steps

Call the `tdd` skill first. The agreed seams are pure helpers, tested with
vitest, and the `api.ts` functions' request shape, if `api.ts` already has
tests (check first; skip that seam if it has none). Keep JSX thin.

1. **Types and API.**
   - Type the Correction:
     `{ start: number; end: number; heard: string; term: string; rule: string; text_start?: number; text_end?: number; confirmed?: boolean }`.
   - Add `confirmCorrection(segmentId, start)`,
     `rejectCorrection(segmentId, start)`, `listRejectedForms()` and
     `deleteRejectedForm(id)` to `api.ts`.
2. **Pure helper.** `correctionPieces(text, corrections)` in a new
   `frontend/src/utils/corrections.ts` returns an ordered list of
   `{ text } | { text, correction }` pieces that covers `text` exactly. Tests:
   - no Corrections gives one piece;
   - two Corrections in the middle;
   - one at offset 0 and one at the end;
   - one without offsets is ignored;
   - out-of-range or overlapping offsets are ignored, and the text is still
     covered exactly once.
3. **Mark and popover.** Render the pieces in `TranscriptView.tsx`, with a
   small `CorrectionMark` component (new file under `components/`) holding
   the popover state and the two actions. If the repo has
   `@testing-library/react`, test one behaviour: clicking the mark does not
   call the Segment's edit handler. Otherwise rely on the pure-helper tests
   and say so in the report.
4. **Settings block.** Load the Rejected Forms in `usePreferencesForm.ts`
   next to `learnedVocab`, then render and delete them in
   `PreferencesTab.tsx`.
5. **Gates.**
   - `cd frontend && npm test` passes, and `npx tsc --noEmit` exits 0;
   - `npm run build` succeeds;
   - `uv run --extra dev pytest -q` from the root still passes.

   Mark 042 DONE in `plans/README.md`.

## Hard boundaries

- In scope: `frontend/src/` (the files named above plus the new helper,
  component and tests) and `plans/README.md`.
- Out of scope: the backend. If a route behaves differently from plan 041,
  STOP.
- Never touch `storage/`, the database, `models/` or `.env`. Never run the
  app against real data.
- Every file change goes through the Edit and Write tools.

## STOP conditions

- The drift check prints changes.
- A route's response lacks `text_start`, `text_end` or `confirmed` where
  plan 041 says they exist.
- Rendering the text as pieces changes how an uncorrected Segment looks
  (same classes, same title, same click-to-edit).

## Done criteria

- `cd frontend && npm test` passes, `npx tsc --noEmit` exits 0, and
  `npm run build` succeeds.
- `uv run --extra dev pytest -q` passes.

## Maintenance note

The marks depend on plan 041's offsets, which are only valid for the derived
text. An edited Segment has no Corrections, so it shows no marks. The
"Never corrected" list is the only place to take back an Undo.
