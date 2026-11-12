# Plan 027: The open Meeting page shows edits made through the API, live

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report; do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat c5cc40a..HEAD -- jobs/__init__.py api/segments.py api/speakers.py api/meetings.py frontend/src/pages/MeetingPage.tsx frontend/src/utils/meetingSocket.ts frontend/src/types.ts`
> Plan 025 is expected to have changed `api/segments.py` and `api/speakers.py`
> (new routes, `_require_editable`). Any other drift is a STOP condition until
> you have compared it against the excerpts below.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: plan 025 (so its new routes also notify; if 025 is not DONE, STOP)
- **Category**: direction
- **Planned at**: commit `c5cc40a`, 2026-10-09
- **Source**: agent-friendliness audit, 2026-10-09. User goal: "modificar os
  trechos em tempo real depois de ter criado o meeting".

## Why this matters

The user wants a coding agent to rename Speakers and correct Segments while
the Meeting is open in the browser, and to see each change appear. Today the
Meeting page reloads only when a Job reaches 100% or fails. An edit made
through the API (by the agent, the CLI, or a second tab) stays invisible until
a manual reload. The app already holds a WebSocket per open Meeting and an
in-process event bus. The edit routes just never publish to it.

## Current state

- `jobs/__init__.py` owns the configured progress bus:

  ```python
  def _progress_adapter():
      if _progress_bus is None:
          raise RuntimeError("Job progress bus has not been configured")
      return _progress_bus
  ```

  and `fail()` shows the house pattern for a best-effort publish:

  ```python
  try:
      (progress_bus or _progress_adapter()).publish(meeting_id, {"type": "error", "error": error})
  except Exception:
      log.exception("Could not publish the failure of Job %s", job_id)
  ```
- `jobs/runners.py` `InProcessBus.publish` is thread-safe
  (`loop.call_soon_threadsafe`). FastAPI runs the sync `def` routes in a worker
  thread, so calling it from a route is safe.
- `api/websocket.py` forwards every bus event for the Meeting to the socket
  unchanged.
- `frontend/src/pages/MeetingPage.tsx` socket handler (lines ~54–64):

  ```tsx
  socket.onmessage = (event) => {
    if (!isCurrent()) return;
    const data: ProgressUpdate = JSON.parse(event.data);
    if (data.type === "ping") return;
    setProgress(data);
    if ((data.type === "progress" && data.progress === 100) || data.type === "error") {
      clearTimeout(refreshTimer);
      refreshTimer = setTimeout(() => {
        if (isCurrent()) fetchMeeting(meetingId, isCurrent);
      }, 500);
    }
  };
  ```

  Every non-ping event goes to `setProgress`, which drives the progress bar.
  A new event type must **not** reach `setProgress`.
- `frontend/src/types.ts`:

  ```ts
  export interface ProgressUpdate {
    type: "progress" | "error" | "ping";
    ...
  }
  ```
- `frontend/src/utils/meetingSocket.ts` holds pure socket decisions
  (`shouldReconnectMeetingSocket`), tested in `meetingSocket.test.ts` with
  vitest. That is the pattern for the new decision function.
- Local form state on the page (`participants`, `domainVocab`) syncs from the
  Meeting only when `currentMeeting?.id` changes, so a refetch does not clobber
  what the user is typing. `TranscriptView` keeps `editingId`/`editText` in
  local state, so a refetch does not cancel an edit in progress.
- Mutating routes after plan 025: `api/segments.py` (`update_segment_text`,
  `update_segment_speaker`, `revert_segment`), `api/speakers.py`
  (`update_speaker`, `merge_speakers`, the add-Speaker route), and
  `api/meetings.py` `update_meeting` (title, vocabulary, participants).

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Backend | `uv run pytest -q tests/test_meeting_api.py` | all pass |
| Backend gate | `uv run pytest -q tests` | 0 failures |
| Frontend tests | `npm test` in `frontend/` | all pass |
| Frontend types | `npx tsc -b` in `frontend/` | exit 0 |

## Scope

**In scope**: `jobs/__init__.py`, `api/segments.py`, `api/speakers.py`,
`api/meetings.py` (`update_meeting` only), `frontend/src/types.ts`,
`frontend/src/utils/meetingSocket.ts`, `frontend/src/utils/meetingSocket.test.ts`,
`frontend/src/pages/MeetingPage.tsx` (the `onmessage` handler only),
`tests/test_meeting_api.py`.

**Out of scope**: partial patching of the store (a full refetch is fine), the
home page list, `api/websocket.py`, and Job progress events.

## Git workflow

- Branch: `advisor/027-live-updates`; commits such as
  `feat(meetings): publish a change event when a Segment or Speaker is edited`
  and `feat(meeting-page): refetch when the Meeting changes elsewhere`.
- Do not push.

## Steps

### Step 1: Publish helper

In `jobs/__init__.py` add:

```python
def notify_meeting_changed(meeting_id: str) -> None:
    """Tell the Meeting's open pages that its Speakers, Segments or details changed outside a Job."""
    try:
        _progress_adapter().publish(meeting_id, {"type": "meeting_changed"})
    except Exception:
        log.exception("Could not publish a change to Meeting %s", meeting_id)
```

**Verify**: `uv run pytest -q tests` → 0 failures.

### Step 2: Call it after every successful commit in the mutating routes

Call `jobs.notify_meeting_changed(<meeting_id>)` right before each route
listed in "Current state" returns its success response, after `db.commit()`.
Use the Segment's or Speaker's `meeting_id`. Never call it on an error path.

**Verify**: new test
`test_segment_edit_publishes_meeting_changed` (pattern:
`test_websocket_forwards_progress_event_in_existing_shape`): open the socket,
wait for one subscriber, `PUT /api/segments/{id}` with `{"text": "novo"}`, and
`websocket.receive_json() == {"type": "meeting_changed"}`.

### Step 3: Pure decision in the frontend

In `frontend/src/types.ts`, extend the union: `type: "progress" | "error" | "ping" | "meeting_changed";`.

In `frontend/src/utils/meetingSocket.ts` add:

```ts
/** What the Meeting page does with one socket event. */
export function meetingSocketAction(event: ProgressUpdate): { showProgress: boolean; refetch: boolean } {
  ...
}
```

Rules:
- `ping` → `{ showProgress: false, refetch: false }`
- `meeting_changed` → `{ showProgress: false, refetch: true }`
- `error` → `{ showProgress: true, refetch: true }`
- `progress` with `progress === 100` → `{ showProgress: true, refetch: true }`
- other `progress` → `{ showProgress: true, refetch: false }`

**Verify**: `npm test` → the five new cases in `meetingSocket.test.ts` pass.

### Step 4: Use it in `MeetingPage.tsx`

Replace the body of `socket.onmessage` after `JSON.parse` with:

```tsx
const action = meetingSocketAction(data);
if (action.showProgress) setProgress(data);
if (action.refetch) {
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(() => {
    if (isCurrent()) fetchMeeting(meetingId, isCurrent);
  }, data.type === "meeting_changed" ? 250 : 500);
}
```

The debounce coalesces a burst of agent edits into one refetch.

**Verify**: `npx tsc -b` in `frontend/` → exit 0; `npm test` → all pass.

### Step 5: Gate

**Verify**: `uv run pytest -q tests` → 0 failures; `npm test` → all pass.

## Test plan

- Backend (`tests/test_meeting_api.py`):
  1. `test_segment_edit_publishes_meeting_changed` (Step 2).
  2. `test_speaker_rename_publishes_meeting_changed`, the same shape with
     `PUT /api/speakers/{id}`.
  3. `test_failed_edit_publishes_nothing`: `PUT` on a PROCESSING Meeting
     (409). Then publish a sentinel `{"type": "ping"}` on the bus yourself and
     assert the first message received is that sentinel.
- Frontend (`meetingSocket.test.ts`): the five rules in Step 3.

## Done criteria

- [ ] `uv run pytest -q tests` exits 0 with the 3 new tests
- [ ] `npm test` exits 0 with the 5 new cases; `npx tsc -b` exits 0
- [ ] `rg -n "notify_meeting_changed" api/` lists every route named in "Current state"
- [ ] Manual (record result in the plan's outcome note, or "not run"): with the
      app running and a completed Meeting open, `curl -X PUT -H "Content-Type: application/json" -d "{\"text\":\"teste ao vivo\"}" http://127.0.0.1:8000/api/segments/<id>`
      changes the line on screen within ~1 s without a reload
- [ ] `plans/README.md` row for 027 updated

## STOP conditions

- Plan 025 is not DONE (its routes would be missed).
- `setProgress` with an unknown event type turns out to be needed elsewhere
  (e.g. `ProgressTracker` reads `type`). Grep `progress.type` in `frontend/src` first.
- The WebSocket test cannot observe the event because the route runs before
  the subscriber registers. Wait on `bus.subscriber_count` as the existing
  test does. If it still fails, report it; do not add sleeps to the app.

## Maintenance notes

- Any new route that changes Speakers, Segments, or Meeting details must call
  `notify_meeting_changed`. Reviewers should check for it.
- If two people edit the same Segment, the last save wins. The refetch shows
  the winner; there is no merge. That is acceptable for a single-user tool.
- `participants`/vocabulary edited by an agent will not refresh the sidebar
  text boxes (they sync on Meeting id only), on purpose: they must not clobber typing.
