# Plan 033: Review Notes on the Meeting page

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report; do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat d9dea5e..HEAD -- frontend/src/`
> No output is expected. Plan 032 changes only the backend. Any frontend drift
> is a STOP condition until compared with the excerpts below.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW (frontend only; the API is plan 032's)
- **Depends on**: plan 032 (if it is not DONE, STOP)
- **Category**: feature
- **Planned at**: commit `d9dea5e`, 2026-10-09
- **Source**: `.scratch/agent-operation/issues/01-review-notes.md`, decided with
  the user on 2026-10-09. Read plan 032's "Decisions" section first. This
  plan does not repeat or change them.

## Why this matters

Plan 032 lets the coding agent leave **Review Notes** (questions, comments,
and suggestions anchored at a time range) on a Meeting. This plan puts them
where the user reviews, on the Meeting page:

- a marker on the Segment, with the audio one click away;
- a **Review** tab in the sidebar to answer questions and accept or dismiss
  suggestions.

The user may also leave a descriptive comment, never a suggestion: they edit
text directly when they want a change. Accepting a text suggestion teaches
Vocabulary by default, and accepting a name suggestion saves the Voice Profile
by default. Both "without" variants exist.

## Current state

- `frontend/src/types.ts` `interface Meeting` has `speakers?`, `segments?`.
  Plan 032 adds `review_notes` to the `GET /api/meetings/{id}` payload.
- `frontend/src/api.ts` uses an axios instance `api` with base `/api`.
  Pattern:

  ```ts
  export async function updateSegmentText(id: string, text: string): Promise<Segment> {
    const { data } = await api.put(`/segments/${id}`, { text });
    return data;
  }
  ```
- `frontend/src/pages/MeetingPage.tsx`:
  - holds `audioRef`;
  - renders `<TranscriptView segments speakers audioRef onUpdate={loadMeeting} />`;
  - has a 288 px sidebar with a tab toggle,
    `useState<"speakers" | "analytics">`, rendered by
    `(["speakers", "analytics"] as const).map(...)` with labels "Speakers" /
    "Stats";
  - shows `SpeakerPanel` or `AnalyticsPanel`.

  Plan 027 refetches the Meeting on every `meeting_changed` socket event, so
  notes the agent creates appear by themselves.
- `frontend/src/components/TranscriptView.tsx`:
  - `seekTo(time)` sets `audioRef.current.currentTime` and plays;
  - each Segment renders as an element with `id="seg-${seg.id}"`;
  - editing state is local (`editingId`, `editText`).
- The UI copy is English ("Speakers", "Stats", "Save", "Cancel"). Keep
  English.
- Frontend tests are pure-function vitest files in `frontend/src/utils/*.test.ts`
  (e.g. `meetingSocket.test.ts`). No component tests exist. Do not add a
  component test framework.

## Plan 032 API this plan consumes

- `GET /api/meetings/{id}` → `review_notes: ReviewNote[]`, each
  `{id, meeting_id, start_time, end_time, author, kind, body, payload, status, answer, reply, created_at, resolved_at}`.
  - `kind` is one of
    `comment|question|text|speaker_name|speaker_move|speaker_merge`.
  - `status` is one of `open|answered|accepted|dismissed|done`.
  - Payloads:
    - `text`: `{expected_text, proposed_text}`;
    - `speaker_name`: `{label, name}`;
    - `speaker_move`: `{target_label}` or `{new_name}`;
    - `speaker_merge`: `{source_label, target_label}`.
- `POST /api/meetings/{id}/notes` `{start_time, end_time, kind:"comment", body, author:"user"}`
- `POST /api/notes/{id}/answer` `{answer}`
- `POST /api/notes/{id}/accept` `{learn?: boolean, save_profile?: boolean}`
  → `{note, warning}`
- `POST /api/notes/{id}/dismiss`
- `POST /api/notes/{id}/done` `{reply?}`

**Verify these against the merged plan 032 code before Step 2** (read
`api/review_notes.py`). If any shape differs, STOP and report.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Unit | `npm test` in `frontend/` | all pass |
| Types | `npx tsc -b` in `frontend/` | exit 0 |
| Build | `npm run build` in `frontend/` | exit 0 |
| Backend gate | `uv run pytest -q` (repo root) | 0 failures (unchanged) |

## Scope

**In scope**:
- `frontend/src/types.ts`, `frontend/src/api.ts`
- `frontend/src/utils/reviewNotes.ts` and `frontend/src/utils/reviewNotes.test.ts` (create)
- `frontend/src/components/ReviewPanel.tsx` (create)
- `frontend/src/components/TranscriptView.tsx`: the marker and the "add note"
  affordance only
- `frontend/src/pages/MeetingPage.tsx`: the third tab and passing props only

**Out of scope**:
- The backend.
- The Speakers and Stats tabs.
- Vocabulary Correction marks (issue 08).
- Split (issue 02).

## Git workflow

- Branch `advisor/033-review-notes-ui`; e.g.
  `feat(meeting-page): a Review tab for Review Notes`. Do not push.

## Steps

### Step 1: Pure logic, test first

`frontend/src/utils/reviewNotes.ts` exports:

```ts
export function noteSegmentId(note: ReviewNote, segments: Segment[]): string | null
// The Segment the note points at: the one whose start and end are both within 1.5 s of the
// note's, nearest by |Δstart|+|Δend|; null if none. (Same rule as the backend's
// segment_for_range; keep the 1.5 constant named NOTE_TOLERANCE_SECONDS with a comment
// pointing at meeting_store.EDIT_TIME_TOLERANCE.)

export function notesBySegment(notes: ReviewNote[], segments: Segment[]): Map<string, ReviewNote[]>
// Only notes whose status is "open" or "answered" (the ones still in play).

export function splitNotes(notes: ReviewNote[]): { open: ReviewNote[]; resolved: ReviewNote[] }
// open = open + answered, sorted by start_time; resolved = accepted/dismissed/done, newest resolved first.

export function noteActions(note: ReviewNote): NoteAction[]
// "answer" | "accept" | "acceptWithoutLearning" | "acceptWithoutProfile" | "dismiss" | "done"
// open question → answer, dismiss
// answered question → (none for the user; the agent closes it)
// open text → accept, acceptWithoutLearning, dismiss
// open speaker_name → accept, acceptWithoutProfile, dismiss
// open speaker_move / speaker_merge → accept, dismiss
// open comment by agent → done
// open comment by user → (none; the agent closes it)
// resolved → none

export function noteSummary(note: ReviewNote): string
// One line for the list:
// text → `"<expected_text>" → "<proposed_text>"`;
// speaker_name → `<label> → <name>`;
// speaker_move → `→ <target_label | new: name>`;
// speaker_merge → `<source> → <target>`;
// question/comment → body.
```

Add the `ReviewNote` type to `types.ts`, and `review_notes?: ReviewNote[]` to
`Meeting`.

**Verify**: `reviewNotes.test.ts` covers each function with worked examples:
- the nearest Segment wins, and a note 5 s away gives `null`;
- resolved notes are excluded from `notesBySegment`;
- the order in `splitNotes`;
- every row of the `noteActions` table;
- one `noteSummary` per kind.

`npm test` was red first, then green.

### Step 2: API functions

In `api.ts` add `listMeetingNotes` (optional; the Meeting payload already
carries them), `createUserComment(meetingId, start, end, body)`,
`answerNote(id, answer)`,
`acceptNote(id, opts: {learn?: boolean; save_profile?: boolean})`
returning `{note, warning}`, `dismissNote(id)` and `closeNote(id, reply?)`,
in the file's existing style.

**Verify**: `npx tsc -b` exits 0.

### Step 3: ReviewPanel

`components/ReviewPanel.tsx`, styled like `SpeakerPanel` (same text sizes
and slate palette). Props:
`{ notes, segments, onUpdate, onSeek(time), meetingId }`.

- The header shows "Review" and the open count.
- The open list comes from `splitNotes(...).open`. Each item shows:
  - the clock of `start_time`, clickable to `onSeek(start_time)`;
  - the author badge (agent/user) and the kind;
  - `noteSummary`, and `body` when it differs from the summary (the agent's
    rationale);
  - `answer` when answered;
  - the buttons from `noteActions`:
    - **Answer** opens a small textarea and **Send** submits it;
    - the accept variants are labeled "Accept", "Accept without teaching"
      and "Accept without saving voice";
    - "Dismiss" and "Done".
  - After any action it calls `onUpdate()`, which refetches. Plan 027's socket
    event also refetches; that is harmless.
  - A `warning` from accept shows inline under the item until the next
    refetch.
  - A 409 shows its `detail` inline. Never use `alert`.
- The resolved list sits in a collapsed "Resolved (N)" section showing the
  status and the answer or reply. It has no actions.
- If `noteSegmentId` returns `null`, the item shows "passage changed" in
  muted text. Accept stays available, because the server decides and returns
  409 with a message.

**Verify**: `npx tsc -b` exits 0; `npm run build` exits 0.

### Step 4: Tab, marker, and the user's comment

- `MeetingPage.tsx`: widen the tab state to
  `"speakers" | "analytics" | "review"` and add the "Review" tab. Show the
  open-note count in the label when it is above 0, e.g. "Review 3". Render
  `<ReviewPanel notes={currentMeeting.review_notes || []} segments=... onUpdate={loadMeeting} onSeek=... meetingId=... />`.
  `onSeek` sets `audioRef.current.currentTime` and plays, like
  `TranscriptView.seekTo`. Optionally, lift a shared `seekTo` helper into
  `MeetingPage` only if that is a trivial move. Otherwise duplicate the
  three lines.
- `TranscriptView.tsx`:
  - Accept a new optional prop `notesBySegment: Map<string, ReviewNote[]>`.
    `MeetingPage` computes it with `notesBySegment(...)`.
  - A Segment with notes in play shows a small marker after its text with
    the count (e.g. "◆ 2"), in the amber used for low confidence.
    Clicking the marker switches the sidebar to the Review tab, through a new
    optional `onShowNotes()` callback that `MeetingPage` passes.
  - On hover, next to the existing edit affordance, show "Note". It opens an
    inline textarea, and Save calls
    `createUserComment(meetingId, seg.start_time, seg.end_time, text)`, then
    `onUpdate()`. Keep it separate from the text-edit state, so editing text
    and writing a note never share `editingId`.
  - `TranscriptView` needs `meetingId` for this. Add it as a prop.

**Verify**: `npx tsc -b` exits 0, `npm test` passes, `npm run build` exits 0.

### Step 5: Gate and manual check

**Verify**: `uv run pytest -q` exits 0 (backend unchanged), and `npm test`
passes.

Manual check, recorded in the outcome note, or write "not run":
1. Build the frontend.
2. Restart the app.
3. On a test Meeting, run
   `uv run python -m transcriber_cli suggest <M> '#3' "texto" --why "teste"`.
4. The open page shows the marker and the Review item within about 1 s.
5. Accept it; the Segment text changes.

Use a throwaway Meeting (e.g. the one titled "test"), never a real one.

## Done criteria

- [ ] `npm test` passes with the new `reviewNotes.test.ts`, which was red first
- [ ] `npx tsc -b` and `npm run build` exit 0
- [ ] `rg -n "\"review\"" frontend/src/pages/MeetingPage.tsx` matches
- [ ] `rg -n "alert\(" frontend/src/components/ReviewPanel.tsx` has no match
- [ ] `plans/README.md` row for 033 updated

## STOP conditions

- Plan 032 is not DONE, or its API shapes differ from the list above.
- Adding the third tab breaks the 288 px sidebar layout so badly that the
  labels do not fit. Report it with a screenshot description; do not
  redesign the sidebar.
- The marker or the note textarea needs changes to the edit flow in
  `TranscriptView` beyond adding siblings.

## Maintenance notes

- `NOTE_TOLERANCE_SECONDS` mirrors the backend's `EDIT_TIME_TOLERANCE`.
  Change both together.
- Issue 08 will add `author: "system"` notes for Vocabulary Corrections.
  `noteActions` should treat them like agent `text` suggestions; add a row
  then.
