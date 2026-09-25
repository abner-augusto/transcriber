# 11 - API Startup Blocks While a Job Is Running

**Source:** manual test of PR #1 on the Windows/GPU machine, 2026-09-24.

**What happened:** the API was restarted while a re-diarization Job ran. The Job
survived (plan 007 works), but uvicorn hung at "Waiting for application startup"
until the worker's next commit, about a minute here. `pg_stat_activity` showed:

- the API waiting on a `relation` lock: `ALTER TABLE meetings ADD COLUMN IF NOT EXISTS vocabulary TEXT`
- the worker `idle in transaction` for 2+ minutes, its last statement a `SELECT meetings.* ...`

**Cause:** two things together.

1. `database.py::init_db` runs its `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
   list on every API start. Postgres takes an ACCESS EXCLUSIVE lock for the
   statement even when the column already exists.
2. During a Job, `meeting_job`'s session holds a transaction open across GPU
   work. `update_progress` commits, and the next attribute access on `meeting`
   starts a new transaction that stays open until the next commit. That can take
   minutes: Diarizer runs, transcription of a long Meeting.

While the ALTER waits, other queries on `meetings` queue behind it, so the API
serves nothing: no Meeting list, no progress page. The longer the stage, the
longer the outage. This predates PR #1: the ALTER list has run on startup since
`4c81f9a` (2026-02-14).

**Blocked by:** none.

**Status:** done — superseded by plans 018/019 (2026-09-25). SQLite's `init_db`
runs `create_all` and idempotent `IF NOT EXISTS` migrations, which take no
exclusive lock on a current schema; WAL lets the API read while a Job child
writes, and `busy_timeout=5000` absorbs short write overlaps. The Postgres
`ALTER TABLE` lock this ticket describes no longer exists. The on-machine
"restart the app mid-Job" check stays open in plan 019.

**Stopgap (this ticket):**
- In `init_db`, read the existing columns once from `information_schema.columns`
  and run an ALTER only for a column that is missing. With the schema already
  current, startup takes no exclusive lock.
- Wrap whatever ALTERs remain in `SET LOCAL lock_timeout = '5s'`, and log a clear
  error instead of hanging if a Job holds the table.
- In the Job path, end the transaction before long GPU work. For example, call
  `db.commit()` (or `db.rollback()` when nothing changed) right after reading what
  the stage needs, so the worker is never `idle in transaction` across a Diarizer
  or Transcriber call. This also stops blocking `VACUUM` and any other DDL.

**Done when:**
- [ ] Restarting the API during a running Job serves `/api/meetings` within a few seconds.
- [ ] `pg_stat_activity` shows no worker session `idle in transaction` during the Diarization stage.
- [ ] A test pins that `init_db` issues no ALTER when all columns exist.

**Carry into plan 018:** the Alembic (or numbered-SQL) runner that replaces the
ALTER list must keep the same guarantee: a no-op migration takes no exclusive
lock, and a real one fails fast instead of waiting on a Job. Plan 019
(one process, a child per Job) changes who holds the connection, not this rule.
