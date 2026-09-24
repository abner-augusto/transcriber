# Plan 020: Remove Redis, Celery, Postgres, and Docker; one start command

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. On a
> STOP condition, stop and report. When done, update `plans/README.md` and
> `.scratch/architecture-review/issues/05-stack-simplification.md`.

## Status

- **Priority**: P3
- **Effort**: M
- **Risk**: MED (installers and docs)
- **Depends on**: plans 018 and 019, and the user having migrated their data
- **Planned at**: commit `284603d`, 2026-09-24
- **Source**: design session 2026-09-24 on tickets 02/04/05

## Decisions (do not re-litigate)

- Delete: Celery adapters, `tasks/celery_app.py`, Redis usage,
  `docker-compose.yml`, the all-in-one image under `docker/` (unused and
  already missing parakeet.cpp and the isolated runtimes), `_start_celery.ps1`,
  and `redis`, `celery`, `psycopg2-binary` from the dependencies (keep
  `psycopg2` only if the migration command must remain; otherwise document
  running it from a pinned older tag).
- Core dependencies move to `pyproject.toml` + `uv.lock` (pinned, like the
  Engine runtimes already are). Engine venvs are created with `uv venv` and
  `uv pip sync` from their existing requirement files.
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
   decision as an ADR ("Single-process local runtime") since it reverses the
   documented hybrid setup.

## Done criteria

- [ ] Clean Windows install with no Docker Desktop, verified by the user
- [ ] One process, one port, one start command
- [ ] `rg -i "celery|redis|docker|postgres" --type py` matches nothing outside the migration command and history docs
- [ ] ADR written
