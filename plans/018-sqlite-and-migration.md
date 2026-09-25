# Plan 018: SQLite with FTS5, and a one-shot migration from Postgres

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. On a
> STOP condition, stop and report. When done, update `plans/README.md` and
> `.scratch/architecture-review/issues/05-stack-simplification.md`.
>
> **Drift check (run first)**: `git diff --stat 284603d..HEAD -- database.py config.py api/search.py models/ migrations/ .env.example INSTALL_WINDOWS.md INSTALL_LINUX.md`

## Status

- **Execution**: DONE — SQLite, FTS5, numbered migrations, and the data copy
  are complete and verified on the user's machine per explicit authorization.

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
  by the migration command through plan 020's optional `postgres-migration`
  dependency group.

## Why this matters

Postgres runs in Docker Desktop for one user. Only two places depend on it:
`api/search.py` (`to_tsvector` / `plainto_tsquery` / GIN index) and
`database.py::init_db` (`ADD COLUMN IF NOT EXISTS`). The `'simple'`
text-search config does not remove accents, which hurts Portuguese search.

## Steps

1. **Schema management**: choose Alembic vs numbered SQL (record the choice
  here). Baseline revision = today's models plus the columns added by
  `init_db`; remove the ALTER list and move the old PostgreSQL-only SQL out of
  `migrations/` once the baseline reproduces them (compare SQLite schema
  against the models).
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

- [x] Fresh SQLite schema initializes without Postgres
- [x] Migration command copies a populated SQLite fixture with matching row
      counts and Segment text checksums; the user's Postgres run remains below
- [x] Search finds accented and unaccented spellings
- [x] One schema-migration mechanism
- [x] The user authorized the migration; row counts, per-Meeting checksums,
      foreign keys, and SQLite search were verified on 2026-09-25

## Schema management decision

Use SQLAlchemy model metadata as the initial schema baseline, followed by a
small numbered Python migration runner for SQLite-only schema operations such
as FTS5 virtual tables and triggers. Alembic would add a dependency without
helping the one-user app's small, local schema changes. The old hand-run
PostgreSQL SQL scripts were moved to `docs/archive/postgres-migrations/` for
historical reference; they are no longer an active migration mechanism.

## STOP conditions

- Any table fails count or checksum verification. Never "fix" data silently.
- A model uses a Postgres-only type that SQLite cannot represent losslessly.

## Outcome

- SQLite WAL, foreign-key enforcement, and 5-second busy timeout are configured
  for every application connection. The default database path is
  `storage/transcriber.db`.
- `database.init_db()` creates the SQLite model baseline and applies numbered
  schema migrations. It refuses to start the application on PostgreSQL; the
  separate migration command can still read it while the existing `.env` is
  unchanged.
- FTS5 search supports accent-insensitive token matching, token prefixes,
  relevance ranking, Meeting grouping, and index triggers for segment edits.
- `scripts.migrate_to_sqlite` copies to a new temporary SQLite file, checks
  source/target schemas, row counts, and per-Meeting Segment text checksums,
  then renames the verified file into place. It does not write to the source
  or overwrite an existing target.
- Verification: the latest backend release suite passed (340 passed; 20 model
  smoke checks deselected); SQLite migration-focused checks also passed.
- **PostgreSQL migration completed 2026-09-25** at the user's request. A
  compressed `pg_dump` and byte-identical `.env` backup are in ignored
  `storage/backups/`; the original Postgres container and data remain intact.
  Counts matched: 44 Meetings, 52,348 Segments, 229 Speakers, 64 Jobs, 12
  Speaker Profiles, and 58 Vocabulary entries. Segment text checksums matched
  for all 44 Meetings; SQLite foreign-key check returned zero errors; search
  for an unaccented Portuguese term returned results. `DATABASE_URL` now points
  to `storage/transcriber.db`.
