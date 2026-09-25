# 10 - Recover PENDING Jobs Whose Broker Message Was Lost

**Source:** review of PR #1 (plan 007), 2026-09-24.

**What to build:** A way out for a Job that stays PENDING forever because its
Celery message never reaches a worker: Redis restarted without persistence,
or the solo worker died after taking the message but before `meeting_job`
marked the Job RUNNING. The Meeting then stays PROCESSING, and
`start_processing` refuses Retry.

**Why it exists now:** before plan 007, API startup failed every PENDING
Job. That also failed Jobs a live worker was about to run, which was the bug
007 fixed. Plan 007 deferred the lost-message case on purpose and must not
start failing PENDING Jobs again.

**Blocked by:** none, but plan 019 (local Job runner, with the Job table as
the queue and PENDING Jobs resumed on restart) removes the broker and with it
this failure mode. Decide whether a stopgap is worth it before 019 lands.

**Status:** done — superseded by plan 019 (2026-09-25). There is no broker
any more: the Job table is the queue, and the local runner resumes PENDING Jobs
in creation order on startup
(`tests/test_local_job_runner.py::test_local_runner_resumes_pending_jobs_in_creation_order`).

**Options:**
- On worker start, re-submit PENDING Jobs whose `celery_task_id` is unknown to
  the broker (needs Celery inspect; plan 007 ruled that out for recovery).
- Let the user retry a Meeting whose only active Job has been PENDING longer
  than N minutes with no worker activity.
- Do nothing until plan 019.
