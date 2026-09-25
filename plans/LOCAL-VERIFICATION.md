# Local verification checklist

This file collects verification that must run on the user's machine or against
the user's private Meetings. Do not commit private recordings, transcripts,
database dumps, model output, or local benchmark reports.

## Before proceeding with the stack migration

| Plan | Local verification | Required evidence |
|------|--------------------|-------------------|
| [014](014-vocabulary-correction.md) | Run the Vocabulary Correction bench below on about eight edited Meetings. | Hits, false changes, and misses per Meeting and in total. Review false changes before accepting the thresholds. |
| [015](015-transcriber-returns-transcription.md) | Run both smoke tiers for parakeet.cpp and faster-whisper large-v3. | All four load/inference combinations pass; inference uses a private local audio file. |
| [018](018-sqlite-and-migration.md) | Back up Postgres, migrate to a new SQLite file, then inspect row counts, transcript checksums, Meetings, and search. | Successful command summary and user confirmation that representative Meetings and search results are correct. Keep the Postgres source and backup until confirmed. |
| [019](019-local-job-runner.md) | Measure load cost for parakeet.cpp, faster-whisper large-v3, pyannote, and ECAPA before implementing the runner. Later, run real Jobs and restart checks on the local GPU. | Four measured load times; then successful end-to-end Jobs for both primary Transcribers, VRAM readings before/after, and confirmation of restart behavior. Stop if per-Job model loading adds more than about 60 seconds to a typical Job. |
| [020](020-remove-legacy-infrastructure.md) | Perform a clean Windows install without Docker Desktop after 018 and 019. | Install and start succeed; one process and one port; existing SQLite data remains visible and searchable. |

## Plan 014: Vocabulary Correction

Run from the repository root:

```powershell
.\venv\Scripts\python.exe bench/vocabulary_correction.py
```

Review the output for every edited Meeting. Record hit, false-change, and miss
counts in the outcome section of plan 014. If false changes exceed hits and a
single threshold adjustment does not fix them, stop and report the results.

## Plan 015: Transcriber smoke tests

Run the `model_load` tier:

```powershell
.\venv\Scripts\python.exe -m pytest tests/engine_smoke/test_load.py --run-engine-smoke --engine-smoke-preset parakeet-tdt-0.6b-v3 --engine-smoke-preset faster-whisper-large-v3 -q
```

Run the `model_inference` tier with a private local audio file:

```powershell
.\venv\Scripts\python.exe -m pytest tests/engine_smoke/test_inference.py --run-engine-smoke --engine-smoke-preset parakeet-tdt-0.6b-v3 --engine-smoke-preset faster-whisper-large-v3 --engine-smoke-audio "C:\path\to\private-audio.wav" -q
```

Record pass/fail for each Preset and tier in plan 015. The smoke code forces
local-only model resolution; it does not upload the audio.

## Plan 018: PostgreSQL to SQLite

1. Stop the app and worker.
2. Create and retain a `pg_dump` backup using the commands in the migration
   section of [INSTALL_WINDOWS.md](../INSTALL_WINDOWS.md).
3. Choose a new target path that does not already exist. Run the migration
   command with the PostgreSQL URL from your `.env`:

   ```powershell
   $sourceDatabaseUrl = "<PostgreSQL URL from .env>"
   .\venv\Scripts\python.exe -m scripts.migrate_to_sqlite --from $sourceDatabaseUrl --to .\storage\transcriber.db
   ```

4. Check the per-table row counts and per-Meeting Segment checksum summary.
   If the command reports any mismatch or schema difference, stop; do not
   point the app at the partial `.migrating` file.
5. Change `DATABASE_URL` in `.env` to `sqlite:///./storage/transcriber.db`,
   start the app, open representative Meetings, and search for accented and
   unaccented Portuguese words. Keep Postgres and the dump until this review
   succeeds.
6. Report the migration date, successful counts/checksums, and confirmation
   that Meetings and search work. Do not put Meeting titles or transcript text
   in this tracked document.

## Plan 019: Local Job runner

Before implementation, measure load time for parakeet.cpp, faster-whisper
large-v3, pyannote, and ECAPA on the same machine that will run Jobs. Record
the measured seconds for each component in plan 019. Do not estimate or use
measurements from another computer. Stop before implementation if the added
per-Job load cost is over the plan's 60-second threshold for a typical Job.

After implementation, run one real Job for each primary Transcriber. Record
whether both complete, compare `nvidia-smi` VRAM use before and after, and
restart the app while a Job is running to verify that RUNNING work fails as
interrupted and PENDING work resumes in creation order. Keep private audio and
transcripts on the machine.

## Plan 020: Clean Windows install

After plans 018 and 019 are verified, use a clean Windows install with Docker
Desktop stopped or absent. Confirm the installer completes, the start command
opens the app on one port, the UI loads, and the migrated Meetings and search
results are present. Record the Windows version and pass/fail in plan 020; do
not include personal Meeting data.
