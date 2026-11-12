# Local verification status

Detailed commands and acceptance conditions live in the consolidated
[verification plan](TEST-PLAN.md). Record only pass/fail, aggregate counts, and
machine/version data here. Do not record titles, transcript text, audio paths,
tokens, or model output.

| Plan | Status | Evidence / remaining work |
|------|--------|---------------------------|
| 014 | Verified, 2026-11-02 | 26 edited Meetings (22 parakeet.cpp, 4 faster-whisper, 2 whisper.cpp): 38 hits, 7 false changes, 310 misses, all hits and false changes on parakeet.cpp. The user's review moved all 7 to hits (two bench scoring gaps, three edits that had kept the mishearing): at least 45 hits, 0 false changes. Starting thresholds stay. |
| 015 | Verified, 2026-11-02 | Parakeet (`parakeet-tdt-0.6b-v3`): `model_load` and `model_inference` passed through pytest on 12 s of local audio. faster-whisper large-v3: the pytest tiers stop at the local-path guard (`model_path` is the hub name `large-v3`; issue architecture-review/15); the same `load_preset`/`infer_preset` run offline against the cached snapshot passed (load 9.3 s, inference 18.8 s, 25 Words). |
| 018 | Verified, 2026-09-25 | 44 Meetings, 52,348 Segments, 229 Speakers, 64 Jobs, 12 SpeakerProfiles, 58 VocabularyEntries; all counts and 44 checksums matched; foreign keys and accented/unaccented search passed. PostgreSQL dump and `.env` copy remain under ignored `storage/backups/`. |
| 019 | Verified, 2026-09-25 | Model load total 19.97 s; Parakeet and faster-whisper real Jobs completed (15.83 s and 21.86 s); GPU memory returned from 1,855 to 1,854 MiB. Process crash, timeout, shutdown, restart recovery, and pending order have automated coverage. 2026-11-02, fresh checkout with a database snapshot: one real Job per Engine (Parakeet 50.7 s, faster-whisper 18.4 s, 20 s clip), VRAM back to the 449 MiB baseline after each. **Hard kill mid-Job fails the gate:** the Job child outlives the killed app, runs alongside the next PENDING Job (8,514 MiB), and overwrites the recovered Job to COMPLETED (issue architecture-review/14). |
| 020 | Windows verified, 2026-11-02 | Windows 11 Pro build 26200, Docker Desktop not running, fresh `git clone` of `1775cfe`: `install.ps1` exit 0 in 10 min (it reused the sibling `whisper.cpp` and `parakeet.cpp` builds already on the machine), `start.ps1` brought up one Python process on port 8000, `/` and `/meetings` serve the built UI, `/api/health` ok. A snapshot of the migrated database lists 90 Meetings, opens their Segments, and search returns 43 results for both `reunião` and `reuniao`. `/api/health` reports `database` and `whisper_cli`, not the SQLite/in-process-bus detail TEST-PLAN.md describes. Clean Linux install still not run. |

Plan 020's Windows gate passed. The clean Linux install (Step 2) is still open.
