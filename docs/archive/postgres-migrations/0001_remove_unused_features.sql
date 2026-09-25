-- 0001 — Remove the six deleted features from the schema.
--
-- Deletes: live recording, LLM speaker-naming, insights, actions, protocol
-- generation, encryption. See docs/adr/0002-llm-features-removed-pending-redesign.md.
--
-- PRESERVES: meetings, segments, speakers, speaker_profiles, vocabulary_entries,
-- and every job belonging to a surviving job type.
--
-- Run against a database you have backed up:
--   docker exec -i transcriber-postgres-1 psql -U transcriber -d transcriber \
--     < migrations/0001_remove_unused_features.sql

BEGIN;

-- Jobs whose job_type no longer exists in the JobType enum. Reading these rows
-- would fail once the Python enum drops the value, so the history goes.
DELETE FROM jobs
WHERE job_type IN ('EXTRACT_INSIGHTS', 'POLISH_PASS', 'FINALIZE_LIVE');

-- Tables belonging to deleted features.
DROP TABLE IF EXISTS meeting_insights;
DROP TABLE IF EXISTS action_results;
DROP TABLE IF EXISTS actions;

-- Meeting columns belonging to deleted features.
ALTER TABLE meetings
  DROP COLUMN IF EXISTS is_encrypted,       -- encryption
  DROP COLUMN IF EXISTS encryption_salt,    -- encryption
  DROP COLUMN IF EXISTS encryption_verify,  -- encryption
  DROP COLUMN IF EXISTS intro_end_time,     -- LLM intro analysis
  DROP COLUMN IF EXISTS mode,               -- live recording
  DROP COLUMN IF EXISTS recording_status,   -- live recording
  DROP COLUMN IF EXISTS polish_history,     -- live recording (polish passes)
  DROP COLUMN IF EXISTS protocol_text;      -- protocol generation

COMMIT;

-- NOTE: the Postgres enum types `meetingstatus` and `jobtype` keep their now-unused
-- labels (RECORDING, FINALIZING, POLISH_PASS, FINALIZE_LIVE, EXTRACT_INSIGHTS).
-- Postgres cannot drop an enum label in place, and leaving them is harmless: no row
-- carries them any more, so SQLAlchemy never has to map them back to Python.
