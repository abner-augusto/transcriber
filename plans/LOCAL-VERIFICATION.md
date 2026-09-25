# Local verification status

Detailed commands and acceptance conditions live in the consolidated
[verification plan](TEST-PLAN.md). Record only pass/fail, aggregate counts, and
machine/version data here. Do not record titles, transcript text, audio paths,
tokens, or model output.

| Plan | Status | Evidence / remaining work |
|------|--------|---------------------------|
| 014 | Pending | Run the Vocabulary Correction bench on about eight edited Meetings; review false changes before accepting thresholds. |
| 015 | Pending | Run load and inference smoke tiers for Parakeet and faster-whisper large-v3 on local models/audio. |
| 018 | Verified, 2026-09-25 | 44 Meetings, 52,348 Segments, 229 Speakers, 64 Jobs, 12 SpeakerProfiles, 58 VocabularyEntries; all counts and 44 checksums matched; foreign keys and accented/unaccented search passed. PostgreSQL dump and `.env` copy remain under ignored `storage/backups/`. |
| 019 | Verified, 2026-09-25 | Model load total 19.97 s; Parakeet and faster-whisper real Jobs completed (15.83 s and 21.86 s); GPU memory returned from 1,855 to 1,854 MiB. Process crash, timeout, shutdown, restart recovery, and pending order have automated coverage. |
| 020 | Pending local release gate | Run the installer from a clean Windows checkout with Docker Desktop stopped or absent; confirm one app process/port, UI, migrated Meetings, and search. |

Plan 020 implementation is ready for the clean Windows install check. After
the local gate passes, update this table and mark Plan 020 complete.
