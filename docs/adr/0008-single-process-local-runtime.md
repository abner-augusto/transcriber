# 0008 - Single-process local runtime

**Status**: accepted

## Context

Transcriber is installed and used by one person on one machine. Its workload
uses one GPU Job at a time. Requiring Docker, PostgreSQL, Redis, Celery, and a
separate frontend server added setup and maintenance costs without serving a
multi-user deployment target. Plans 018 and 019 replaced the database and Job
execution model with SQLite and a child process per Job.

## Decision

- Run one FastAPI application process with an in-process Job runner and
  thread-safe WebSocket progress bus. The runner starts one spawned child
  process per Job; child exit releases model and GPU memory.
- Store application data in SQLite with WAL, foreign keys, and FTS5.
- Serve the built frontend and client-side routes from FastAPI on the same
  port. Vite remains the frontend development server.
- Use `uv` with `pyproject.toml` and `uv.lock` for core Python dependencies.
  Keep Qwen3-ASR and VibeVoice in their separate pinned Engine environments.
- Remove Docker, PostgreSQL, Redis, and Celery from the runtime and installers.
- Keep the one-time PostgreSQL importer and its driver as an optional install
  extra for upgrades from older versions. The source database is read-only to
  the importer.
- Keep parakeet.cpp and faster-whisper as the primary Engines (ADR-0007).

## Consequences

- The app starts with one command and no background infrastructure services.
- RUNNING Jobs fail as interrupted after restart; PENDING Jobs resume in
  creation order.
- SQLite is for this single-user local runtime. A multi-user server deployment
  would need a new architecture decision.
- Legacy PostgreSQL migration requires explicitly installing the optional
  `postgres-migration` dependency group.
