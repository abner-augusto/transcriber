# 02 - Make Celery Task Failures Truthful

**Plan:** `plans/002-make-celery-failures-truthful.md`

**What to build:** Preserve the existing `meeting_job` database and Redis failure
handling while allowing genuine processing exceptions to propagate to Celery.
Celery, the domain Job, and the Meeting must agree that processing failed.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] A failed processing task is recorded as failed by Celery rather than returned as a successful error dictionary.
- [ ] The Job and Meeting are marked `FAILED` before the exception propagates.
- [ ] Failure persistence and Redis error publication happen exactly once.
- [ ] Reprocessing tasks follow the same exception policy.
- [ ] Successful task return values and lifecycle transitions remain unchanged.
- [ ] Integration tests cover processing failure, reprocessing failure, and success.

