# Verification plan

This document is the single checklist for release verification of Plans 018,
019, and 020, plus the outstanding local gates from Plans 014 and 015. Never
commit private audio, transcript text, database dumps, tokens, or model output.

Latest local verification (2026-09-25): 340 backend tests passed and 20 model
smoke checks were deselected; all 36 frontend tests passed and the frontend
production build succeeded. `uv lock --check`, Bash syntax checks, PowerShell
parser checks, and `git diff --check` passed. The clean Windows installer gate
is still pending.

## Automated checks

Run from the repository root after code changes:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -m "not model_load and not model_inference" -q
```

Expected: all ordinary backend tests pass. This covers SQLite schema and FTS,
migration behavior, API routes, Preferences/RunConfig, Job ordering, child
success/failure/crash/timeout, shutdown, progress relay, and startup recovery.

Build and test the frontend:

```powershell
Push-Location frontend
npm ci
npm run build
npm test -- --run
Pop-Location
```

Run `npm ci` in a fresh checkout or with frontend development servers stopped.
For an active development checkout, use a temporary worktree so npm does not
replace files held by a running Node process.

The API server must serve `/` and a client-side URL such as `/meetings`, while
continuing to serve `/api/health`, `/api/settings`, and built assets.

Check patch formatting and dependency lock consistency:

```powershell
git diff --check
uv lock --check
```

## Plan 018: PostgreSQL to SQLite

For a database from an older PostgreSQL release, retain a custom-format dump
before migration. Install the optional driver when migrating:

```powershell
uv sync --locked --extra dev --extra postgres-migration
$sourceDatabaseUrl = "<PostgreSQL URL from the old .env>"
.\.venv\Scripts\python.exe -m scripts.migrate_to_sqlite --from $sourceDatabaseUrl --to .\storage\transcriber.db
```

The command must report matching table counts and per-Meeting Segment text
checksums, then confirm SQLite foreign keys. Point `.env` at
`sqlite:///./storage/transcriber.db` only after those checks pass. Start the
app, open representative Meetings, and search for both `reunião` and
`reuniao`. Keep PostgreSQL and its dump until the UI review succeeds. Do not
put counts from another user's database in tracked documentation.

For the already migrated local database, verified evidence (2026-09-25): 44
Meetings, 52,348 Segments, 229 Speakers, 64 Jobs, 12 SpeakerProfiles, and 58
VocabularyEntries copied; row counts and all 44 Segment text checksums match;
SQLite foreign-key check returned zero errors; accented/unaccented FTS search
returned results. The source dump and pre-migration `.env` backup remain under
ignored `storage/backups/`.

## Plan 019: Local Job runner

Run the deterministic process and restart tests as part of the ordinary suite
above. Then, on the local machine, run:

```powershell
.\.venv\Scripts\python.exe -m scripts.measure_job_model_load
.\.venv\Scripts\python.exe -m scripts.local_job_smoke
nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits
```

The smoke creates a temporary database and storage directory, selects a local
audio file without printing its path or content, and runs Parakeet and
faster-whisper through the production runner. Confirm both Jobs complete and
GPU memory returns to its idle baseline. Automated checks cover stopping an
active child, marking RUNNING work failed during recovery, and resuming
PENDING work in creation order. Do not commit local audio or resulting text.

Verified on 2026-09-25: model loads were 0.00 s for the Parakeet adapter,
9.16 s for faster-whisper large-v3, 9.38 s for pyannote, and 1.43 s for ECAPA
(19.97 s for Python model loads). Real Jobs completed in 15.83 s (Parakeet)
and 21.86 s (faster-whisper large-v3). GPU memory was 1,855 MiB before and
1,854 MiB after both Jobs.

## Plan 020: Single-process install and runtime

On Windows with Docker Desktop stopped or absent, use a fresh checkout or a
separate empty worktree and run:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

Then run `.\start.ps1`. Confirm the built UI loads on port 8000, `/api/health`
reports SQLite and the in-process progress bus, existing migrated Meetings
remain visible and searchable, and only the app process is needed. Record the
Windows version and pass/fail in `plans/LOCAL-VERIFICATION.md`, without
including personal Meeting data.

The clean Windows install remains a local release gate until verified on a
fresh checkout. Do not treat Linux tests or an existing virtual environment as
that evidence.

## Outstanding local gates

Plan 014's Vocabulary Correction bench and Plan 015's four model load/inference
smoke combinations are still listed in `plans/LOCAL-VERIFICATION.md`. Run
those only with the user's corrected Meetings or local audio fixture, and
record aggregate outcomes without transcript content.
