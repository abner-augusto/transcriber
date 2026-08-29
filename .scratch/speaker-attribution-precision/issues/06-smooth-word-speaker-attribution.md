# 06 - Smooth Per-Word Speaker Attribution

**What to build:** Smooth the sequence of per-Word Speaker assignments so isolated timestamp errors do not split a coherent Segment, while sustained interruptions remain separate and attributable.

**Blocked by:** 01 - Remove Earlier-Speaker Bias in Overlap Attribution; 02 - Use Exclusive Diarization for Attribution and Preserve Overlap Metadata.

**Status:** completed

- [x] Attribution scores are based on overlap evidence for each candidate Speaker.
- [x] Switching Speaker between adjacent Words incurs a tunable penalty in the intended range.
- [x] The switch penalty is waived when the inter-Word gap exceeds the configured pause threshold for a new speaking turn.
- [x] An isolated one-Word flap is smoothed back into the surrounding Speaker assignment.
- [x] A sustained interruption spanning multiple Words remains assigned to the interrupting Speaker and creates its own Segment boundary.
- [x] Existing sentence, pause, maximum-duration, nearest-Turn, and `UNKNOWN` behavior remains intact.
- [x] Tests cover isolated flips, real interruptions, long gaps, ties, and empty input.
