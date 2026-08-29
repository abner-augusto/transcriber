# 04 - Add Optional CTC Forced Alignment

**What to build:** Add an opt-in higher-precision timing path that aligns the generated transcript against the audio with a Portuguese-capable CTC model, so users can reduce Word-boundary slop beyond what whisper.cpp timestamps provide.

**Blocked by:** None — can start immediately; independent alternative to ticket 03.

**Status:** done

- [x] A configured forced-alignment option transfers precise start and end times onto existing Words without changing their text or order.
- [x] The default processing path remains unchanged unless higher-precision alignment is enabled.
- [x] The selected pt-BR-compatible alignment model and its local lifecycle are documented and validated before processing.
- [x] Alignment failure is reported clearly and follows an explicit fallback policy rather than silently producing partial timings.
- [x] Tests cover successful alignment, punctuation and word-order preservation, disabled mode, and failure handling.

