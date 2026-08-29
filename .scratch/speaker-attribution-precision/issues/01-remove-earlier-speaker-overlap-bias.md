# 01 - Remove Earlier-Speaker Bias in Overlap Attribution

**What to build:** Make Word attribution deterministic when multiple Turns overlap a Word, so an earlier Speaker does not win solely because that Turn is encountered first. Preserve nearest-Turn attribution for Words that fall into small diarization gaps.

**Blocked by:** None — can start immediately.

**Status:** completed

- [x] Equal-overlap Words are resolved by an explicit deterministic policy that is independent of Turn iteration order.
- [x] Strictly greater overlap still selects the Turn with the greatest overlap.
- [x] Words with no overlap retain the existing nearest-Turn tolerance and `UNKNOWN` fallback behavior.
- [x] Regression tests cover equal overlap, unequal overlap, reversed Turn order, diarization gaps, and no Turns.
