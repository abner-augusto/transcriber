# Plan 020: Remove Redis, Celery, Postgres, and Docker; one start command

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. On a
> STOP condition, stop and report. When done, update `plans/README.md` and
> `.scratch/architecture-review/issues/05-stack-simplification.md`.

> **Local-only steps**: see "Run locally by the user" in `plans/README.md`. An agent
> stops before them, leaves their boxes unchecked, and never writes estimated numbers.

## Status

- **Execution**: IN PROGRESS — Plans 018 and 019 are complete and the local
  data migration is verified. The clean Windows install remains a release gate.
  See [verification plan](TEST-PLAN.md).

- **Priority**: P3
- **Effort**: M
- **Risk**: MED (installers and docs)
- **Depends on**: plans 018 and 019, and the user having migrated their data
- **Planned at**: commit `284603d`, 2026-09-24
- **Source**: design session 2026-09-24 on tickets 02/04/05

## Decisions (do not re-litigate)

- Delete the Celery adapters, `tasks/celery_app.py`, Redis usage, Docker files,
  `_start_celery.ps1`, and Celery/Redis dependencies. Keep
  `psycopg2-binary` only in the optional `postgres-migration` group.
- Core dependencies move to `pyproject.toml` + `uv.lock`. Install with
  `uv sync --locked`; Engine venvs use `uv venv` and `uv pip install` with
  their checked-in requirement files and the matching CPU/CUDA Torch build.
- FastAPI serves `frontend/dist` (`StaticFiles` + SPA fallback) on one port.
  `npm run dev` with the Vite proxy remains the development loop only.
- `start.ps1` / `start.sh` start one process and open the browser; no Docker
  check. Installers stop requiring Docker Desktop.
- Keep Python for the backend (rejected: rewriting in another language —
  `.scratch/architecture-review/README.md`).
- ADR-0007: the core install keeps the parakeet.cpp build and faster-whisper.

## Steps

1. Remove Celery/Redis code paths and dependencies; suite passes without
   them installed.
2. `pyproject.toml` + `uv.lock`; update `install.ps1` / `install.sh`,
   `INSTALL_*.md`, README. Verify a clean install on Windows (user) and
   Linux (CI or this environment).
3. Static frontend serving + SPA fallback; one start command.
4. Delete Docker files and the Docker sections of the docs. Record the
   decision in [ADR-0008](../docs/adr/0008-single-process-local-runtime.md),
   which replaces the earlier hybrid setup.

## Done criteria

- [ ] Clean Windows install with Docker Desktop stopped or absent, verified on a fresh checkout
- [ ] Clean Linux install from a fresh checkout (Step 2; not yet run anywhere)
- [x] One FastAPI process, one port, one start command; Jobs run in their planned child process
- [x] Celery and Redis packages/adapters are removed; PostgreSQL is an explicit migration extra only
- [x] ADR written

The latest local code verification passed 340 backend tests, 36 frontend tests,
the production frontend build, and lock/syntax checks. The complete installer
has not been run from a fresh checkout with Docker Desktop stopped or absent;
that machine-level acceptance criterion remains open.
