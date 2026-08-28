# 02 - Use Exclusive Diarization for Attribution and Preserve Overlap Metadata

**What to build:** Use pyannote Community-1's exclusive diarization output as the single-speaker source for Segment attribution, while retaining the original overlapping diarization output so the transcript can identify affected speech. Make clustering preferences observable and truthful instead of silently accepting unsupported parameters.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] When Community-1 provides exclusive diarization, Words and Segments are attributed from those exclusive Turns.
- [ ] The original overlapping diarization and the exclusive diarization are both persisted in the Meeting's raw diarization data.
- [ ] The meeting response exposes enough overlap information for the transcript UI to mark content affected by overlapping speech without changing transcript text or timestamps.
- [ ] Full processing and re-diarization use the same exclusive-attribution behavior.
- [ ] The Community-1 path and fallback diarizer path remain usable when exclusive output is unavailable.
- [ ] Clustering preferences are applied only when supported, and logs expose the effective parameters and any ignored values.
- [ ] Tests cover exclusive output selection, overlap metadata persistence/exposure, fallback output, and unsupported clustering parameters.
