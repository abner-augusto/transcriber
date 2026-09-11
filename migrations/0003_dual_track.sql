-- 0003 — A Meeting can carry dual-track audio (mic + system).
--
-- Dual-track Meetings store the raw source files in mic_audio_filepath and
-- system_audio_filepath. For a stereo file both point to the same file and the
-- pipeline splits it into the two mono tracks. is_dual_track flags the Meeting so
-- the pipeline knows to run the dual-track flow (deterministic host + neural remote).
--
-- Run against a database you have backed up:
--   docker exec -i transcriber-postgres-1 psql -U transcriber -d transcriber \
--     < migrations/0003_dual_track.sql

BEGIN;

ALTER TABLE meetings ADD COLUMN IF NOT EXISTS mic_audio_filepath VARCHAR;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS system_audio_filepath VARCHAR;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS is_dual_track BOOLEAN;

COMMIT;
