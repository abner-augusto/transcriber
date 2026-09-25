-- 0002 — A Meeting can pin the Preset it is transcribed with.
--
-- NULL means "use the default Preset at the time the Job runs", which is what every
-- existing Meeting gets. Pinning one is how the same audio gets transcribed by two
-- Engines for comparison.
--
-- Replaces `whisper_model`, which was written with a default of 'medium' and never
-- read by anything.
--
-- Run against a database you have backed up:
--   docker exec -i transcriber-postgres-1 psql -U transcriber -d transcriber \
--     < migrations/0002_meeting_preset.sql

BEGIN;

ALTER TABLE meetings ADD COLUMN IF NOT EXISTS preset_id VARCHAR;
ALTER TABLE meetings DROP COLUMN IF EXISTS whisper_model;

COMMIT;

-- NOTE: raw_transcription and raw_diarization are not migrated. A Meeting transcribed
-- before the Transcriber port stored whisper's coarse segments as a bare JSON list;
-- new ones store {"engine", "preset", "words"} and {"engine", "turns"}. Both shapes are
-- read by tasks.shared.words_from_stored / turns_from_stored, so old Meetings can still
-- be re-diarized and re-identified without being re-transcribed.
