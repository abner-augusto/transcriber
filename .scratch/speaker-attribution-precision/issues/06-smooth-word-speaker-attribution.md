# 06 - Smooth Per-Word Speaker Attribution

**What to build:** Smooth the sequence of per-Word Speaker assignments so isolated timestamp errors do not split a coherent Segment, while sustained interruptions remain separate and attributable.

**Blocked by:** 01 - Remove Earlier-Speaker Bias in Overlap Attribution; 02 - Use Exclusive Diarization for Attribution and Preserve Overlap Metadata.

**Status:** ready-for-agent

- [ ] Attribution scores are based on overlap evidence for each candidate Speaker.
- [ ] Switching Speaker between adjacent Words incurs a tunable penalty in the intended range.
- [ ] The switch penalty is waived when the inter-Word gap exceeds the configured pause threshold for a new speaking turn.
- [ ] An isolated one-Word flap is smoothed back into the surrounding Speaker assignment.
- [ ] A sustained interruption spanning multiple Words remains assigned to the interrupting Speaker and creates its own Segment boundary.
- [ ] Existing sentence, pause, maximum-duration, nearest-Turn, and `UNKNOWN` behavior remains intact.
- [ ] Tests cover isolated flips, real interruptions, long gaps, ties, and empty input.
