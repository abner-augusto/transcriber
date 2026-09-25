# 05 - Simplify the Runtime Stack

**Source:** architecture review 2026-09-24, stack section.

**What to build:** Replace infrastructure sized for multi-user servers with
what a single-user local tool needs:

| Today | Proposal |
|-------|----------|
| Postgres 16 in Docker | SQLite (WAL) + FTS5 (`unicode61 remove_diacritics 2`) |
| Redis + Celery (`--pool=solo`, prefetch 1) | Job table as the queue + child process per Job (ticket 04) |
| Docker Compose | removed |
| uvicorn + celery + vite (3 processes) + 2 containers | one Python process serving the built frontend via `StaticFiles` |
| unpinned `requirements.txt` for the core | `uv` with `pyproject.toml` + `uv.lock`; engine venvs synced with `uv pip sync` |
| two migration mechanisms (`init_db` ALTER list + `migrations/*.sql`) | one (Alembic or a numbered SQL runner) |
| hand-written `frontend/src/types.ts` | generated from FastAPI's OpenAPI (`openapi-typescript`) |

**Why:** Concurrency is already 1 and the GPU allows one Job at a time. On
Windows, Docker Desktop is a prerequisite only for Postgres and Redis. The
only Postgres-specific code is the `tsvector` search in `api/search.py` and
`ADD COLUMN IF NOT EXISTS` in `database.py`. FTS5 with diacritics removal
also finds "reuniao" for "reunião", which the current `'simple'` config does
not.

**Blocked by:** 02 (Job module), 04 (child process). The SQLite + FTS5 swap
can be done independently and first.

**Status:** in-progress (Plan 018 implementation; user data migration pending)

**Plans:** `plans/018-sqlite-and-migration.md` (SQLite + FTS5, manual migration command)
and `plans/020-remove-legacy-infrastructure.md` (remove Redis/Celery/Postgres/Docker, `uv`,
one start command). Decided 2026-09-24: Windows native, single user, one GPU.

**Constraints:**
- ADR-0001: everything stays local.
- ADR-0007: the core install keeps the parakeet.cpp build and faster-whisper
  (which also supplies Silero VAD).
- Keep Python for the backend (see README "Explicitly rejected").

**Resolved in Plan 018:** existing PostgreSQL Meetings move through a manual,
one-shot SQLAlchemy copy into a new SQLite file. Source row counts and per-Meeting
Segment text checksums must match before the app is pointed at SQLite.

**Open questions for the exploration session:**
- Keep `vite dev` for development only, or also drop Node from the dev loop?
- Desktop packaging (Tauri shell + Python sidecar): revisit only after the
  single-process change.

**Acceptance criteria (draft):**
- [ ] Fresh Windows install without Docker
- [ ] Search matches accented and unaccented Portuguese spellings
- [ ] `start.ps1` / `start.sh` start one process
