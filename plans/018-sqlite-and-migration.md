# Plan 018: SQLite with FTS5, and a one-shot migration from Postgres

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. On a
> STOP condition, stop and report. When done, update `plans/README.md` and
> `.scratch/architecture-review/issues/05-stack-simplification.md`.
>
> **Drift check (run first)**: `git diff --stat 284603d..HEAD -- database.py config.py api/search.py models/ migrations/ .env.example INSTALL_WINDOWS.md INSTALL_LINUX.md`

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: HIGH (the user's data; many Meetings recorded)
- **Depends on**: none technically; step 2 of the stack migration (see
  plan 017 "Where this sits"). Can run before or after 017.
- **Planned at**: commit `284603d`, 2026-09-24
- **Source**: design session 2026-09-24 on tickets 02/04/05

## Decisions (do not re-litigate)

- Target database: SQLite in WAL mode, file under storage
  (`storage/transcriber.db`), `DATABASE_URL=sqlite:///...` in `.env`.
- Search: FTS5 with `tokenize="unicode61 remove_diacritics 2"`, so
  "reuniao" finds "reunião".
- One migration mechanism: replace the `init_db` ALTER list and
  `migrations/*.sql` with Alembic (or a numbered-SQL runner if Alembic proves
  heavy on Windows; decide in step 1 and record why).
- Data migration is a **manual command**:
  `python -m scripts.migrate_to_sqlite --from <postgres url> --to <sqlite path>`.
  It copies every table, verifies row counts per table (and a checksum of
  Segment text per Meeting), prints a summary, and never touches the source.
  The user keeps a `pg_dump` until they confirm. Audio under `storage/` does
  not move.
- The app supports **only** SQLite after this plan; Postgres stays readable
  by the migration command until plan 020 removes `psycopg2`.

## Why this matters

Postgres runs in Docker Desktop for one user. Only two places depend on it:
`api/search.py` (`to_tsvector` / `plainto_tsquery` / GIN index) and
`database.py::init_db` (`ADD COLUMN IF NOT EXISTS`). The `'simple'`
text-search config does not remove accents, which hurts Portuguese search.

## Steps

1. **Schema management**: choose Alembic vs numbered SQL (record the choice
   here). Baseline revision = today's models plus the columns added by
   `init_db`; delete the ALTER list and `migrations/*.sql` once the baseline
   reproduces them (compare `sqlite3 .schema` against the models).
2. **Engine settings**: SQLite `connect_args={"check_same_thread": False}`,
   `PRAGMA journal_mode=WAL`, `foreign_keys=ON`, `busy_timeout=5000` on
   connect. Drop the Postgres pool args.
3. **Search**: an FTS5 virtual table over `segments(text)` with triggers to
   keep it in sync; `api/search.py` ranks with `bm25`. Tests: accent-insensitive
   match, prefix match, ranking, results grouped by Meeting as today.
4. **Migration command** with tests against a Postgres fixture if one is
   available, otherwise against a SQLite→SQLite copy plus a unit test of the
   verification step. Document in `INSTALL_WINDOWS.md` / `INSTALL_LINUX.md`
   ("Migrating from Postgres"), including the `pg_dump` backup step.
5. **Defaults**: `.env.example` and `config.py` default to SQLite; the test
   suite no longer needs Postgres for anything.

## Done criteria

- [ ] Fresh install works with no Postgres
- [ ] Migration command copies a populated database with matching counts and checksums
- [ ] Search finds accented and unaccented spellings
- [ ] One schema-migration mechanism
- [ ] The user ran the migration on their data and confirmed (record date here)

## STOP conditions

- Any table fails count or checksum verification. Never "fix" data silently.
- A model uses a Postgres-only type that SQLite cannot represent losslessly.
