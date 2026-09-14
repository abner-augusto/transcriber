# 02 - Make Celery Task Failures Truthful

**Plan:** `plans/002-make-celery-failures-truthful.md`

**What to build:** Preserve the existing `meeting_job` database and Redis failure
handling while allowing genuine processing exceptions to propagate to Celery.
Celery, the domain Job, and the Meeting must agree that processing failed.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] A failed processing task is recorded as failed by Celery rather than returned as a successful error dictionary.
- [x] The Job and Meeting are marked `FAILED` before the exception propagates.
- [x] Failure persistence and Redis error publication happen exactly once.
- [x] Reprocessing tasks follow the same exception policy.
- [x] Successful task return values and lifecycle transitions remain unchanged.
- [x] Integration tests cover processing failure, reprocessing failure, and success.

**Verification:** Task lifecycle tests pass (4 tests), related pipeline regressions
pass (25 tests), and the resource-limited backend suite passes (183 tests).
