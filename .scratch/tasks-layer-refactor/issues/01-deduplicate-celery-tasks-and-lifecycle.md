# 01 - Deduplicate Celery Tasks Pipeline and Job Lifecycle

**What to build:** 
Consolidate the duplicated Celery task logic across `process_meeting.py` and `reprocess_task.py`:
1. Extract `_rebuild_speakers_and_segments` into `tasks/shared.py` and use it across all tasks, guaranteeing edit preservation.
2. Introduce a `meeting_job(meeting_id, job_id)` context manager in `tasks/shared.py` for database session management, status transitions, Redis events, and error handling.
3. Unify `rediarize_task` and `reidentify_task` core logic into a single internal handler (`reprocess_meeting(..., rerun_diarization=...)`).
4. Clean up the accidentally duplicated `raw_transcription_data` block in `process_meeting.py`.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] Move `_rebuild_speakers_and_segments` to `tasks/shared.py` with edit-preservation support.
- [x] Implement `@contextmanager def meeting_job(meeting_id: str, job_id: str)` in `tasks/shared.py` managing DB session, `RUNNING`/`COMPLETED`/`FAILED` transitions, and Redis error/progress events.
- [x] Migrate `process_meeting_task` to use `meeting_job` and the shared rebuild function.
- [x] Migrate `rediarize_task` and `reidentify_task` to share an internal execution function controlled by `rerun_diarization: bool`.
- [x] Remove duplicate `raw_transcription_data` assignment in `tasks/process_meeting.py`.
- [x] Verify that all existing tests pass without regressions (97/97).
