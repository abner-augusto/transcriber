# 12 - Reprocessing Resets Speaker Names the User Set

**Source:** manual test of PR #1 on the Windows/GPU machine, 2026-09-24.

**What happened:** on a dual-track Meeting, the host Speaker (label `HOST`) had
been renamed by hand to the user's name (`identified_by = "manual"`). After
Re-diarize it was named "You" again (`identified_by = "host_track"`). Every other
Speaker was renamed too.

**Cause:** `tasks/shared.py::rebuild_speakers_and_segments` deletes every Speaker
of the Meeting and creates new ones from the Speaker Namer's output. It preserves
edited Segment text, not Speaker names. This predates PR #1.

**Why it is not a one-line fix:** what "the same Speaker" means depends on the
Reprocessing.

- **Re-identify** keeps the Turns, so labels are stable and a manual name can be
  carried over by label.
- **Re-diarize** produces new Turns, so `SPEAKER_02` before and after may be
  different people. Carrying names over by label would mislabel them. The
  dual-track `HOST` label is the exception: it is deterministic (mic track), so
  its manual name can always be kept.
- Plan 014's "Re-apply Vocabulary" already requires that it "must not reset
  user-renamed Speakers". Whatever this ticket decides should be the same rule.

**Blocked by:** none. Coordinate with plan 014, which touches the same rebuild
path.

**Status:** needs-exploration

**Questions for the session:**
- On Re-diarize, should manual names be matched to new Speakers by Turn overlap
  (the new Speaker that covers most of the old one's speaking time), and only
  above some overlap threshold?
- Should a manual rename also save a Voice Profile, so that re-identification
  recovers it for free?
- Should the UI warn before a Reprocessing that will drop manual names?
