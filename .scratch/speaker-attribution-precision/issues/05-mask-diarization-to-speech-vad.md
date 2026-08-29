# 05 - Constrain Diarization to Speech-VAD Bounds

**What to build:** Use a separate speech VAD to constrain diarization Turns to regions that contain speech, reducing boundary hallucinations caused by mismatched ASR and diarization VAD behavior.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] Speech-VAD bounds are computed from the same Meeting audio before Turns are used for attribution.
- [x] Each diarization Turn is clipped or discarded so it cannot extend outside speech bounds.
- [x] Short gaps and adjacent speech regions are handled without dropping valid Words at boundaries.
- [x] The behavior is applied consistently during full processing and re-diarization.
- [x] VAD model/configuration requirements and resource impact are documented.
- [x] Tests cover clipping, discarded non-speech Turns, boundary-adjacent Words, empty VAD output, and normal speech.
