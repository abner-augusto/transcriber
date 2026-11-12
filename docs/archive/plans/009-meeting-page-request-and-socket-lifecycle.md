# Plan 009: Stop stale Meeting fetches and zombie WebSocket reconnects

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 40b455a..HEAD -- frontend/src/pages/MeetingPage.tsx frontend/src/store.ts frontend/src/types.ts frontend/package.json`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `40b455a`, 2026-09-17

## Outcome (2026-09-24)

Done in `0d3ffb1`. `loadMeeting()` stays the no-argument callback the child
panels call; it delegates to `fetchMeeting(id, isCurrent)`, which the
lifecycle effect calls with its `cancelled` guard. The reconnect timer
re-evaluates `shouldReconnectMeetingSocket` when it fires, so visibility is
checked both at close time and at reconnect time, as the old code did.
`wsRef` was removed; the socket is local to the effect.

## Why this matters

`MeetingPage` loads a Meeting and opens a progress WebSocket keyed by `id`.
`loadMeeting` is not cancelled, so navigating A → B can apply A's response
onto B. `ws.onclose` always schedules `connectWebSocket()` after 3s when the
tab is visible; the effect cleanup calls `ws.close()`, which fires `onclose`
and reconnects after unmount. Two effects both close `wsRef` on `id` change.
The page then talks to a socket for a Meeting the user is not looking at,
and Zustand `currentMeeting` can show the wrong transcript.

## Current state

- `frontend/src/pages/MeetingPage.tsx:36-97` — two `useEffect`s on `[id]`;
  `loadMeeting` / `connectWebSocket` close over `id` without a generation
  token; `onclose` reconnects unless code `4004`.
- `frontend/src/store.ts` — global `currentMeeting` / `progress`; cleanup
  sets both to `null`. Keep that.
- Meeting status no longer includes `finalizing` (YAGNI cleanup already
  landed). Do not restore it.
- Frontend tests today are pure utils via vitest, no jsdom:
  `frontend/src/utils/vocabulary.test.ts`. Match that: extract a tiny
  reconnect policy and test it without React Testing Library.

Excerpts:

```tsx
// MeetingPage.tsx:36-97
useEffect(() => {
  if (!id) return;
  loadMeeting();
  return () => {
    wsRef.current?.close();
    setCurrentMeeting(null);
    setProgress(null);
  };
}, [id]);

useEffect(() => {
  if (!id) return;
  connectWebSocket();
  return () => {
    wsRef.current?.close();
  };
}, [id]);

function connectWebSocket() {
  ...
  ws.onclose = (event) => {
    if (event.code === 4004) return;
    setTimeout(() => {
      if (document.visibilityState === "visible") connectWebSocket();
    }, 3000);
  };
}
```

Repo conventions: TypeScript, no new dependencies. Vitest `describe`/`it`
as in `frontend/src/utils/vocabulary.test.ts`. Domain: this page shows one
**Meeting**; progress events are for that Meeting's **Job**.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Frontend unit tests | `npm test` (cwd `frontend`) | all pass, including new file |
| Frontend typecheck/build | `npm run build` (cwd `frontend`) | `tsc -b && vite build` exit 0 |

Do not run backend pytest unless you accidentally touched Python (you must not).

## Scope

**In scope**:

- `frontend/src/pages/MeetingPage.tsx`
- `frontend/src/utils/meetingSocket.ts` (create)
- `frontend/src/utils/meetingSocket.test.ts` (create)

**Out of scope**:

- Adding `jsdom`, `@testing-library/react`, or any npm dependency.
- Restoring `recording` / `finalizing` / live-session types.
- `HomePage.tsx`, `SettingsDialog.tsx` (Plan 011).
- Backend websocket (`api/websocket.py`).
- Changing Zustand shape.
- `engines/`, Python files.

## Git workflow

- Branch: `advisor/009-meeting-page-lifecycle`
- Commit: `fix(frontend): drop stale meeting fetches and socket reconnects`
- Do NOT push unless instructed.

## Steps

### Step 1: Extract and test reconnect policy

Create `frontend/src/utils/meetingSocket.ts`:

```ts
export const MEETING_NOT_FOUND_CLOSE = 4004;
export const RECONNECT_DELAY_MS = 3000;

export function shouldReconnectMeetingSocket(opts: {
  closeCode: number;
  cancelled: boolean;
  visibilityState: string;
}): boolean {
  if (opts.cancelled) return false;
  if (opts.closeCode === MEETING_NOT_FOUND_CLOSE) return false;
  return opts.visibilityState === "visible";
}
```

Create `frontend/src/utils/meetingSocket.test.ts` modeled on
`vocabulary.test.ts`:

- `cancelled: true` → false (even if visible and code 1000)
- `closeCode: 4004` → false
- `visibilityState: "hidden"` → false
- `cancelled: false`, code 1006, `"visible"` → true

**Verify**: from `frontend`, `npm test` → all pass.

### Step 2: One effect, generation guard, cancelled reconnect

In `MeetingPage.tsx`:

1. Collapse the two `[id]` effects into **one**.
2. Hold `cancelled` in a `let` inside the effect (not a ref that survives
   the next effect without reset). Set `cancelled = true` in cleanup.
3. `loadMeeting` must capture `const requestedId = id`. After every `await`,
   if `cancelled` or `requestedId !== id` (use a ref `idRef.current = id`
   updated at the top of the effect), do not call `setCurrentMeeting` /
   `setProgress`.
4. `connectWebSocket`:
   - assign `wsRef.current = ws` as today
   - `onclose` uses `shouldReconnectMeetingSocket({ closeCode: event.code,
     cancelled, visibilityState: document.visibilityState })`
   - if it should reconnect, `setTimeout(..., RECONNECT_DELAY_MS)` and the
     timeout callback must check `cancelled` **again** before calling
     `connectWebSocket`
   - cleanup: `cancelled = true`; `clearTimeout` the reconnect timer
     (store the timer id in a variable closed over by cleanup); then
     `ws.close()`.
5. Keep `setCurrentMeeting(null)` and `setProgress(null)` on cleanup.
6. `ws.onmessage` for `progress === 100` / `error` still delays
   `loadMeeting()`; that delayed call must also no-op when `cancelled`.

Do not add exhaustive-deps eslint comments that ignore `id`. Do not put
`loadMeeting` in the dependency array if that re-subscribes every render;
keep functions inside the effect or wrap in `useCallback` keyed on `id`.

**Verify**: `npm run build` in `frontend` → exit 0.

### Step 3: Confirm no second effect remains

Search `MeetingPage.tsx` for `connectWebSocket` and `useEffect`. There must
be a single `useEffect` whose dependency array is `[id]` (plus store
setters only if you must; prefer not listing zustand setters).

**Verify**: `rg "useEffect" frontend/src/pages/MeetingPage.tsx` → one
`useEffect` for meeting id lifecycle (other effects such as vocabulary
hydrate on `currentMeeting?.id` may remain).
`npm test` in `frontend` → pass.

## Test plan

- New `frontend/src/utils/meetingSocket.test.ts` as in step 1.
- Pattern: `frontend/src/utils/vocabulary.test.ts`.
- No component render tests (no jsdom in this repo).
- Verification: `npm test` in `frontend` → all pass including the new file.

## Done criteria

- [ ] `npm test` in `frontend` exits 0
- [ ] `npm run build` in `frontend` exits 0
- [ ] `shouldReconnectMeetingSocket` is used from `MeetingPage.tsx`
- [ ] Meeting id lifecycle uses a single `useEffect`
- [ ] Cleanup sets a cancelled flag that blocks both reconnect and
      `setCurrentMeeting` after await
- [ ] Reconnect timeout is cleared on cleanup
- [ ] No new npm dependencies (`git diff frontend/package.json` empty)
- [ ] No files outside the in-scope list are modified
- [ ] `plans/README.md` status row for 009 updated

## STOP conditions

- Current-state excerpts no longer match.
- You believe you must add jsdom or Testing Library.
- `MeetingPage.tsx` has been rewritten (large uncommitted UI work) so the
  two-effect structure is gone already.
- Fix appears to require changing `api/websocket.py` close codes.

## Maintenance notes

- Operator may later delete `finalizing` UI (YAGNI). This plan must still
  work if that status string never arrives.
- Reviewer: walk the unmount path — close must not schedule reconnect.
- Plan 011 splits Home/Settings only; do not move this hook into those
  files.
