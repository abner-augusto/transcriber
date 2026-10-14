# The app keeps no original recording

**Status**: accepted (2026-10-14, plan 045). Amended by ADR-0012.

The originals of every Meeting live outside the app, in the project folder of
that meeting. The app is not their archive. Once a Meeting finishes processing
it keeps `audio.wav`, the 16 kHz mono audio it derived (a mix for a dual-track
Meeting), and drops the uploaded sources and the intermediate processed tracks.
Uncompressed WAV kept forever had filled the disk: 33 GB over 56 Meetings.

## Consequences

- Playback, Voice Profile clips, speaker naming, Re-identify, Re-apply
  vocabulary, Re-diarize and Full reprocess of a single-track Meeting all run
  from `audio.wav`.
- A dual-track Meeting cannot be Re-diarized, fully reprocessed or duplicated
  from `audio.wav`: the host/remote split needs the two tracks, and the mix
  cannot give them back. ADR-0012 answers that with a Source Reference to the
  originals, which those actions read from where they live. Without a reference
  the API answers 400 (`Meeting.reprocessable` is false).
- A Meeting that has not been processed, or whose Job failed, keeps its sources
  so a retry works.
- Duplicate & reprocess shares files with hard links instead of copying them.
- Database paths follow the files: `mic_audio_filepath` and
  `system_audio_filepath` are NULL once the sources are dropped.
- Where the original lives is recorded as a Source Reference (ADR-0012).
