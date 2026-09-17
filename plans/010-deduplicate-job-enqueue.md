# Plan 010: One helper to claim a Meeting and enqueue its Job

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 40b455a..HEAD -- api/meetings.py tasks/process_meeting.py tasks/reprocess_task.py tasks/shared.py tests/test_meeting_api.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/007-move-job-recovery-off-api-startup.md, plans/008-rediarize-dual-track-meetings.md
- **Category**: tech-debt
- **Planned at**: commit `40b455a`, 2026-09-17

## Why this matters

`start_processing`, `rediarize_meeting`, and `reidentify_meeting` each copy
the same sequence: 400 if already `PROCESSING`, atomic UPDATE to
`PROCESSING`, insert Job `PENDING`, `task.delay`, save `celery_task_id`.
A later change to the claim (the lock Plan 007 restored) is easy to apply
in one route and miss the others. After Plan 008 the dual-track diarization
nestin is gone from reprocess; this plan does **not** re-open that. It only
collapses the API enqueue/claim duplication and the four-line
`attribution_turns` ternary that process and reprocess still copy.

## Current state

- `api/meetings.py:224-237` — `_queue_full_processing` creates a
  `PROCESS_MEETING` Job and delays `process_meeting_task`.
- `api/meetings.py:240-267` — `start_processing` atomic UPDATE then
  `_queue_full_processing`.
- `api/meetings.py:325-360` — `rediarize_meeting` copies the UPDATE + Job +
  `rediarize_task.delay` + `celery_task_id`.
- `api/meetings.py:363-398` — `reidentify_meeting` same copy for
  `reidentify_task`.
- `api/meetings.py:273-322` — `duplicate_meeting` sets `PROCESSING` on a
  brand-new row then `_queue_full_processing` (no atomic claim needed).
- `tasks/process_meeting.py:159-165` and `tasks/reprocess_task.py:60-64` —
  identical `attribution_turns = exclusive if exclusive else bounded`.
  `tasks/shared.py:541-546` already has `attribution_turns_from_stored` for
  **JSON**; do not overload it. Add a tiny list helper next to it.
- Tests: `tests/test_meeting_api.py` covers vocabulary PUT and blocked
  preset; it does not cover the claim. Add claim tests with a fake
  `.delay`.

Domain: **Job** (`JobType.PROCESS_MEETING | REDIARIZE | REIDENTIFY`).
Celery is the mechanism; the helper name should say Job, not task, except
the `delay_fn` parameter.

Excerpts:

```python
# api/meetings.py:254-266 (claim + enqueue for process)
rows = db.execute(
    update(Meeting)
    .where(Meeting.id == meeting_id)
    .where(Meeting.status != MeetingStatus.PROCESSING)
    .values(status=MeetingStatus.PROCESSING)
)
if rows.rowcount == 0:
    db.rollback()
    raise HTTPException(409, "Meeting is already being processed")
job = _queue_full_processing(db, meeting)
```

```python
# api/meetings.py:339-359 (same claim, different JobType) — duplicated again
# at 377-397 for reidentify
```

Repo conventions: FastAPI `HTTPException` with numeric codes as used in
this file (`400` already processing, `409` lost the race). Keep both
messages. Fake `.delay` returning an object with `.id` like:

```python
class FakeAsyncResult:
    id = "celery-fake-id"
```

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Meeting API tests | `.\venv\Scripts\python.exe -m pytest tests/test_meeting_api.py -q` | all pass |
| Task tests | `.\venv\Scripts\python.exe -m pytest tests/test_task_failure_lifecycle.py tests/test_pyannote_exclusive.py tests/test_reprocess_dual_track.py -q` | all pass |
| Ordinary backend suite | `.\venv\Scripts\python.exe -m pytest -m "not model_load and not model_inference" -q` | exit 0 |
| Diff whitespace | `git diff --check` | exit 0 |

## Scope

**In scope**:

- `api/meetings.py`
- `tests/test_meeting_api.py`
- `tasks/shared.py` (add `choose_attribution_turns(bounded, exclusive)` only)
- `tasks/process_meeting.py` (call that helper; no other restructuring)
- `tasks/reprocess_task.py` (call that helper; no other restructuring)

**Out of scope**:

- Changing HTTP paths or Job payload shape.
- Dual-track / native diarization control flow (Plan 008).
- Job recovery (Plan 007).
- `main.py` preferences endpoint.
- Frontend.
- `engines/`.
- Extracting a giant `finalize_transcript` from process/reprocess.

## Git workflow

- Branch: `advisor/010-deduplicate-job-enqueue`
- Commit: `refactor(api): share meeting job claim and enqueue`
- Do NOT push unless instructed.

## Steps

### Step 1: Tests for claim + enqueue as they behave today

In `tests/test_meeting_api.py`, using the existing sqlite `db_session`
fixture and `TestClient(app)`:

1. `test_process_rejects_when_already_processing` — Meeting
   `PROCESSING` → POST `/process` → 400 `"Already processing"`, no Job row.
2. `test_process_lost_race_returns_409` — if easier, skip a true race;
   instead monkeypatch the UPDATE to return `rowcount == 0` after the
   400-check passed (Meeting `UPLOADED`). Expect 409 and zero Jobs.
   If that monkeypatch is too brittle, STOP and report rather than
   inventing a thread race.
3. `test_process_records_celery_task_id` — monkeypatch
   `process_meeting_task.delay` to append args and return
   `FakeAsyncResult()`. POST `/process` on `UPLOADED` → 200, Job
   `PENDING` or at least created, `celery_task_id == "celery-fake-id"`,
   Meeting `PROCESSING`.
4. Same delay fake for `/rediarize` (needs `raw_transcription` JSON with
   a `words` list) and `/reidentify` (needs `raw_transcription` and
   `raw_diarization`).

Blocked-preset test already in this file must keep passing.

**Verify**: `.\venv\Scripts\python.exe -m pytest tests/test_meeting_api.py -q`
→ new tests pass against current duplicated code.

### Step 2: Introduce `_claim_meeting_for_processing` and `_enqueue_job`

In `api/meetings.py`:

```python
def _claim_meeting_for_processing(db: Session, meeting_id: str) -> None:
    from sqlalchemy import update
    rows = db.execute(
        update(Meeting)
        .where(Meeting.id == meeting_id)
        .where(Meeting.status != MeetingStatus.PROCESSING)
        .values(status=MeetingStatus.PROCESSING)
    )
    if rows.rowcount == 0:
        db.rollback()
        raise HTTPException(409, "Meeting is already being processed")

def _enqueue_job(db: Session, meeting: Meeting, job_type: JobType, delay_fn) -> Job:
    job = Job(meeting_id=meeting.id, job_type=job_type, status=JobStatus.PENDING)
    db.add(job)
    db.commit()
    result = delay_fn(meeting.id, job.id)
    job.celery_task_id = result.id
    db.commit()
    return job
```

Replace `_queue_full_processing` with
`_enqueue_job(db, meeting, JobType.PROCESS_MEETING, process_meeting_task.delay)`.

`start_processing`: keep 404, keep 400 already processing, keep
`_require_usable_preset`, then `_claim_meeting_for_processing`, then
`_enqueue_job`.

`rediarize_meeting` / `reidentify_meeting`: keep their 404/400 precondition
checks (including raw_transcription / raw_diarization). Replace the copied
UPDATE+Job+delay with claim + `_enqueue_job(..., rediarize_task.delay)` /
`reidentify_task.delay`.

`duplicate_meeting`: keep creating the copy as `PROCESSING` (no claim on
the source). Use `_enqueue_job` instead of `_queue_full_processing`.

Delete `_queue_full_processing`.

**Verify**: `.\venv\Scripts\python.exe -m pytest tests/test_meeting_api.py -q` → pass.

### Step 3: One-liner attribution helper

In `tasks/shared.py` next to `attribution_turns_from_stored`:

```python
def choose_attribution_turns(
    bounded_turns: list[Turn],
    exclusive_turns: list[Turn] | None,
) -> list[Turn]:
    if exclusive_turns is not None and len(exclusive_turns) > 0:
        return exclusive_turns
    return bounded_turns
```

Replace the duplicated ternary in `process_meeting.py` and
`reprocess_task.py`. Do not change `build_segments` or Speaker Namer calls
beyond that argument.

**Verify**: `.\venv\Scripts\python.exe -m pytest tests/test_build_segments.py tests/test_pyannote_exclusive.py tests/test_task_failure_lifecycle.py tests/test_reprocess_dual_track.py -q`
→ pass.

## Test plan

- New cases in `tests/test_meeting_api.py` as step 1.
- Pattern: existing `test_blocked_preset_cannot_create_or_queue_job`.
- No new test file required.
- Verification: ordinary backend suite command above.

## Done criteria

- [ ] `rg "_queue_full_processing" api/meetings.py` returns no matches
- [ ] `rg "celery_task_id = result.id" api/meetings.py` matches exactly once
      (inside `_enqueue_job`)
- [ ] `start_processing`, `rediarize_meeting`, `reidentify_meeting` all call
      `_claim_meeting_for_processing` and `_enqueue_job`
- [ ] `choose_attribution_turns` used in both task modules
- [ ] `.\venv\Scripts\python.exe -m pytest -m "not model_load and not model_inference" -q` exits 0
- [ ] No files outside the in-scope list are modified
- [ ] `plans/README.md` status row for 010 updated

## STOP conditions

- Plan 007 or 008 not actually landed and the live enqueue/diarization
  code does not match this plan's excerpts (run the drift check; if 007/008
  changed these files, update excerpts mentally only if the claim/delay
  sequence is still the same — if Plan 008 still inlines dual-track inside
  `reprocess_task`, that is fine; do not merge it into the API helper).
- You "simplify" by dropping the 400 already-processing check or the 409
  race check. Keep both.
- You move enqueue into `tasks/` (API must keep creating the Job row before
  delay so the worker can load it).
- Need to touch `engines/` or frontend.

## Maintenance notes

- Reviewer: `_enqueue_job` must `commit` before `delay` so the worker can
  see the Job. That order is load-bearing (same as today).
- Duplicate-meeting still skips claim on the source; correct.
- Future cancel/revoke should wrap `_enqueue_job`, not the three routes.
