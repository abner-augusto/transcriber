# Plan 043: Corrections stand out, and the Review tab lists them all

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report; do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**: confirm plan 042 is DONE in `plans/README.md`,
> then run
> `git diff --stat 1f8e538..HEAD -- frontend/src/components/CorrectionMark.tsx frontend/src/components/ReviewPanel.tsx frontend/src/pages/MeetingPage.tsx frontend/src/utils/`.
> Any output is a STOP condition until compared with the excerpts below.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: 042
- **Category**: UI
- **Planned at**: commit `1f8e538`, 2026-10-10
- **Source**: the user, 2026-10-10, after trying plan 042:
  - "deixa a cor de destaque da sugestão da palavra mais contrastada com o roxo
    da página, pois fica muito fraco de identificar";
  - "na aba review, cria uma categoria listando todas as sugestões de
    correção, embaixo das notas de review, para consultar direto na aba sem
    precisar procurar em uma reunião longa".

## Decisions

- **Mark contrast.** In `CorrectionMark.tsx`, an unconfirmed mark loses the
  violet, which blends into the page's violet accents. It becomes cyan and
  thicker, with a faint background:
  `decoration-cyan-300 decoration-2 bg-cyan-400/10 rounded-sm`. Keep
  `underline decoration-dotted underline-offset-2`. A confirmed mark stays as
  it is (`decoration-slate-500/50`, no background). Amber stays reserved for
  low confidence.
- **Review tab section** "Vocabulary Corrections":
  - It sits below everything the notes render, including the "Resolved"
    toggle.
  - The heading row shows the title, plus `{n} to review` when
    unconfirmed ones exist.
  - The section is hidden when the Meeting has no Correction with offsets.
  - Unconfirmed Corrections are listed first, in time order. Confirmed ones
    sit behind a collapsed toggle, `▸ Confirmed ({n})`, styled like the
    "Resolved" toggle.
  - Each row has:
    - the time, a button calling `onSeek(correction.start)`, styled like a
      note's time;
    - the Segment as `#order`;
    - `heard → term`, with `heard` in slate and `term` in white;
    - Confirm (only when unconfirmed) and Undo buttons, with the same
      `title`s as `CorrectionMark`.

    Errors show the API `detail` under the row via `apiErrorMessage`, as the
    notes do. After a success, call `onUpdate()`.
  - A Correction without `text_start`/`text_end` is not listed. Undo needs
    the offsets, and such data predates plan 041.
  - The sidebar tab's badge keeps counting open notes only. The
    Corrections' count lives in the section heading.
- **No duplicated logic.** Confirm and undo are already in `api.ts`
  (`confirmCorrection`, `rejectCorrection`). Both the mark and the list call
  them. A small pure helper builds the list.

## Current state

- `frontend/src/components/CorrectionMark.tsx` (plan 042) renders the mark
  with

  ```tsx
  className={`underline decoration-dotted underline-offset-2 cursor-pointer ${
    confirmed ? "decoration-slate-500/50" : "decoration-violet-400/70"
  }`}
  ```
  Its buttons have
  `title="Teach this form: it will be corrected the same way in future Meetings"`
  and
  `title="Put back what was heard and never correct this form to this term again"`.
- `frontend/src/components/ReviewPanel.tsx` takes
  `{ notes, segments, onUpdate, onSeek, meetingId }`.
  - It renders the open notes, then a "Resolved" toggle
    (`{showResolved ? "▾" : "▸"} Resolved ({resolved.length})`).
  - A note's time button is
    `className="font-mono text-slate-500 hover:text-violet-400 transition"`.
  - It already receives `segments`. Each Segment has `id`, `order` and
    `corrections?: Correction[]`, typed in `frontend/src/types.ts`.
- `frontend/src/utils/reviewNotes.ts` and its test are the pattern for a
  pure helper next to the panel.

## Steps

Call the `tdd` skill first. The agreed seam is the pure helper, tested with
vitest; JSX stays thin.

1. **Helper.** Add `meetingCorrections(segments)` in a new
   `frontend/src/utils/meetingCorrections.ts`. It returns
   `{ toReview: Entry[], confirmed: Entry[] }`, where
   `Entry = { segmentId: string; order: number; correction: Correction }`.
   Each list is sorted by `correction.start`, and Corrections without
   offsets are skipped. Tests:
   - empty segments give two empty lists;
   - mixed confirmed and unconfirmed Corrections across Segments are split
     and time-sorted;
   - offset-less Corrections are excluded.
2. **Section.** Render it in `ReviewPanel.tsx` per the Decisions. Use the
   helper through `useMemo` over `segments`. Track busy and error state per
   row with a key of `` `${segmentId}:${correction.start}` ``, mirroring
   `busyId` and `errors` for notes.
3. **Contrast.** Change the unconfirmed class in `CorrectionMark.tsx` as in
   the Decisions.
4. **Gates.** In `frontend/`:
   - `npm test` passes;
   - `npx tsc --noEmit` exits 0;
   - `npm run build` succeeds.

   Then run `uv run --extra dev pytest -q` from the root, and mark 043 DONE
   in `plans/README.md`.

## Hard boundaries

- In scope: `CorrectionMark.tsx`, `ReviewPanel.tsx`, the new helper and its
  test, and `plans/README.md`.
- Out of scope: the backend, `MeetingPage.tsx` (no prop change is needed),
  and the tab badge.
- Never touch `storage/`, the database, `models/` or `.env`. Never run the
  app against real data.
- Every file change goes through the Edit and Write tools.

## STOP conditions

- The drift check prints changes.
- `ReviewPanel` does not receive the Segments' `corrections` (the prop is
  missing or stripped).

## Done criteria

- `cd frontend && npm test` passes, `npx tsc --noEmit` exits 0, and
  `npm run build` succeeds.
- `uv run --extra dev pytest -q` passes.

## Maintenance note

The list and the mark act on the same Correction through the same routes, and
the WebSocket refresh keeps both in sync. A future count of Corrections in
the tab badge belongs in `MeetingPage.tsx`, computed with the same helper.
