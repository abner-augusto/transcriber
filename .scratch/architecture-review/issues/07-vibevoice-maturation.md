# 07 - Mature and Evaluate VibeVoice

**Source:** ADR-0007 — vibevoice is experimental until evaluated.

**What to build:** A repeatable evaluation of the vibevoice Engine on the
user's real Meetings, and the fixes it surfaces, so it can be promoted to
secondary or primary (or kept experimental with a recorded reason).

**Why:** ADR-0005 reports 0.56% adjusted WDER on one benchmark recording, but
the first integrated runs regressed (wrong sample rate and streaming
geometry, see the ADR-0005 addendum). Throughput is ~55 s per 60 s window at
NF4 on the RTX 5070 Ti. It has not been trusted for daily use yet.

**Blocked by:** None. Benefits from plan 012 (native Turns go through the
same Diarization stage as pyannote, so comparisons are like for like).

**Status:** needs-exploration

**Open questions for the exploration session:**
- Which recordings form the evaluation set (length, number of speakers,
  dual-track or not)?
- Metrics: WER on names/technical terms, WDER (`bench/wder.py`), wall-clock,
  peak VRAM.
- Compare native VibeVoice Turns against pyannote Turns on the same Words.

**Acceptance criteria (draft):**
- [ ] Evaluation script in `bench/` with results recorded in the repo
- [ ] Decision recorded in ADR-0007 (promote, keep experimental, or remove)
