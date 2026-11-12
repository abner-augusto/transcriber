# Plan 034: Make Review Notes visible on the transcript and the audio bar

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report; do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 959e7e1..HEAD -- frontend/src/`
> Any output is a STOP condition until compared with the excerpts below.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW (frontend only)
- **Depends on**: 033 (DONE)
- **Category**: UX
- **Planned at**: commit `959e7e1`, 2026-10-09
- **Source**: the user, after using the Review tab for the first time,
  2026-10-09. They asked for a clearer visual sign that a passage has a note.
  They chose both of these:
  - a highlighted Segment;
  - clickable marks on the audio progress bar, colored by state.

## Why this matters

Plan 033's only in-transcript sign is a 10 px "◆ N" glyph at the right edge of
the Segment row. On a 1-hour Meeting the user cannot see where the notes are
without opening the Review tab. Two signs fix that:

- the Segment itself is highlighted;
- the audio bar shows the notes across the whole Meeting.

Both are colored by who must act next.

## Decisions (from the user)

- A Segment with a note in play gets a **colored left bar and a light
  background tint**. The "◆ N" glyph stays.
- The audio **progress bar gets one mark per note in play**, at its
  `start_time`. Clicking a mark seeks there.
- **Color by state**:
  - **amber** means waiting for the user: the note has a user action, i.e.
    `noteActions(note)` is non-empty;
  - **sky/blue** means waiting for the agent: an `answered` question, or an
    open comment written by the user.
  - A Segment with both kinds shows amber, because the user's attention
    comes first.

## Current state

- `frontend/src/utils/reviewNotes.ts`:
  - `notesBySegment(notes, segments)` returns `Map<segmentId, ReviewNote[]>`
    with the notes in play only (`open`/`answered`);
  - `noteActions(note)` returns the user's actions; it is empty for an
    answered question, a user comment, and resolved notes;
  - `NOTE_TOLERANCE_SECONDS`.

  Tests are in `reviewNotes.test.ts`.
- `frontend/src/components/TranscriptView.tsx`, the Segment row:

  ```tsx
  const segNotes = notesBySegment?.get(seg.id);
  ...
  <div id={`seg-${seg.id}`}
    className={`group flex items-start gap-2 rounded-lg px-3 py-1.5 -mx-3 transition-all duration-200 ${
      isActive ? "bg-violet-500/10 border border-violet-500/20"
               : "border border-transparent hover:bg-slate-800/30"}`}>
  ```

  The "◆ N" button uses `text-amber-500/80` and calls `onShowNotes`.
- `frontend/src/components/AudioPlayer.tsx`:
  - Props: `{ meetingId, audioRef }`.
  - It keeps `duration` in state.
  - The progress bar is a `div.flex-1.relative.group` holding a
    `div.h-1.5 ... overflow-hidden` fill bar and an
    `<input type="range" className="absolute inset-0 w-full h-full opacity-0 cursor-pointer">`
    overlay. The overlay covers the bar, so marks that must take clicks have
    to sit **above** it (`z-10`) and be small. Dragging anywhere else on the
    bar must keep working.
- `frontend/src/pages/MeetingPage.tsx`:
  - computes `segmentNotes = notesBySegment(reviewNotes, currentMeeting.segments || [])`;
  - renders `<AudioPlayer meetingId={currentMeeting.id} audioRef={audioRef} />`.

## Scope

**In scope**: `frontend/src/utils/reviewNotes.ts` and `reviewNotes.test.ts`,
`frontend/src/components/TranscriptView.tsx` (row classes only),
`frontend/src/components/AudioPlayer.tsx` (one optional prop plus the marks),
and `frontend/src/pages/MeetingPage.tsx` (passing the prop).

**Out of scope**: the backend, `ReviewPanel.tsx`, and any player behavior
other than the marks.

## Git workflow

Branch `advisor/034-note-indicators`, commit
`feat(meeting-page): highlight passages with Review Notes`. Do not push.

## Steps

### Step 1: Pure helpers, test first

In `reviewNotes.ts` add:

```ts
export type NoteTone = "user" | "agent";

/** Who acts next on a note in play: the user when they have an action, else the agent. null if resolved. */
export function noteTone(note: ReviewNote): NoteTone | null

/** The tone for a Segment's notes: "user" wins over "agent"; null for none. */
export function segmentTone(notes: ReviewNote[] | undefined): NoteTone | null

/** One mark per note in play, for the audio bar. */
export function noteMarks(notes: ReviewNote[]): { id: string; time: number; tone: NoteTone }[]
```

**Verify**: tests with worked examples:
- an open agent question gives `"user"`;
- an answered question gives `"agent"`;
- an open user comment gives `"agent"`;
- an open agent comment gives `"user"`;
- a resolved note gives `null`;
- `segmentTone` with mixed notes gives `"user"`;
- `noteMarks` skips resolved notes and keeps `start_time`.

`npm test` must be red first, then green.

### Step 2: Highlighted Segment

In `TranscriptView`, compute `const tone = segmentTone(segNotes)`. When
`tone` is set, add a left bar and a tint to the row, keeping the active-row
look intact:
- `user`: `border-l-2 border-l-amber-400/80 bg-amber-500/5`;
- `agent`: `border-l-2 border-l-sky-400/70 bg-sky-500/5`.

Tailwind needs the classes written out literally (no string building of
class names). When the row is also active, the violet active background
wins and the left bar stays. Color the "◆ N" glyph by the same tone
(`text-amber-500/80` or `text-sky-400/80`).

**Verify**: `npx tsc -b` exits 0 and `npm run build` exits 0.

### Step 3: Marks on the audio bar

- `AudioPlayer` gets an optional prop
  `marks?: { id: string; time: number; tone: NoteTone }[]`.
- When `duration > 0`, render one `<button>` per mark inside the
  progress-bar container (`div.flex-1.relative.group`), positioned
  absolutely:
  - `left: ${(time / duration) * 100}%`;
  - centered vertically;
  - about `w-1.5 h-3 rounded-sm`, with `z-10`;
  - colored `bg-amber-400` or `bg-sky-400`.
- `title` is "Review note: waiting for you" or "Review note: waiting for the
  agent".
- `onClick` seeks: `audioRef.current.currentTime = time`.
- `MeetingPage` passes `marks={noteMarks(reviewNotes)}`.

**Verify**: `npx tsc -b`, `npm run build` and `npm test` all pass.

### Step 4: Gate

**Verify**: `npm test` and `uv run pytest -q` (backend unchanged) pass.

## Done criteria

- [ ] `npm test` passes with the new helper tests, which were red first
- [ ] `npx tsc -b` and `npm run build` exit 0
- [ ] `rg -n "border-l-amber|border-l-sky" frontend/src/components/TranscriptView.tsx` matches
- [ ] `rg -n "marks" frontend/src/components/AudioPlayer.tsx frontend/src/pages/MeetingPage.tsx` matches both
- [ ] `plans/README.md` row for 034 updated

## STOP conditions

- The marks cannot take clicks without breaking the range input's dragging.
  Describe what happens; do not replace the input.
- Drift in the listed files.
