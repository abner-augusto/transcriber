# 01 - Explore a Visual Revamp of the Interface

**Source:** user request, 2026-10-29. Prompted by the impeccable design hook flagging
`UploadDialog.tsx` for an "AI color palette" (violet gradients, cyan on dark).

**What to explore:** A new visual direction for the whole frontend (Home, Meeting page,
Upload, Settings), replacing the default dark slate + violet/cyan look that the 18
components and pages under `frontend/src` share. The UI has no design system
(no `DESIGN.md`, no tokens): colors are Tailwind utility classes repeated per component.

**Why:** The current look reads as generic AI-generated UI. The app is used for long
reviews of transcripts (reading, naming Speakers, correcting Words), so legibility and
calm matter more than flash.

**How to run the exploration:**
1. `/impeccable` first: critique the current UI and agree on a direction (palette,
   typography, density, light/dark) with the user. Record the result as `DESIGN.md`.
2. `/prototype`: build throwaway mockups of the two screens that matter most, the
   Meeting page (transcript + Speakers + audio player) and the Upload dialog, in two or
   three candidate directions, for the user to compare side by side.
3. Write the chosen direction into this issue, or a spec beside it in this folder (tokens
   first, then screens one at a time), then flip this issue to `ready-for-agent`.

**Blocked by:** none.

**Status:** needs-exploration

**Open questions for the exploration session:**
- Light theme, dark theme, or both?
- Keep Tailwind utilities or introduce design tokens (CSS variables / Tailwind theme)?
- Which semantic colors must survive the change: low-confidence underline (amber),
  Correction mark, Speaker colors, Job status in `ProgressTracker`?
- Does the revamp also cover layout and information architecture, or color and type only?

**Acceptance criteria (for the exploration itself):**
- [ ] `DESIGN.md` records the agreed direction.
- [ ] Prototypes of the Meeting page and Upload dialog were shown and one direction chosen.
- [ ] This issue, or a spec beside it, lists the implementation steps; this issue is `ready-for-agent`.
