# Long audio is chunked inside the whisper adapter too

**Status**: accepted

ADR-0003 chunks parakeet.cpp because its compute graph cannot fit a long clip in VRAM, and says
whisper.cpp needs none of this because it windows internally. That is true for VRAM — it is not true
for wall-clock time, and a real Meeting recording found the gap.

A ~54-minute Meeting failed with `whisper-cli failed: ...` after the log showed
`whisper_backend_init_gpu: no GPU found` — a run where whisper-cli's own CUDA detection came back
empty despite the GPU being available and detected on every other invocation observed. Run on CPU
instead, `large-v3-turbo` at beam-size 5 over 54 minutes of audio does not reliably finish inside
`TRANSCRIBE_TIMEOUT_SECONDS` (1800s), and one subprocess call means that failure loses the whole
recording's transcript, not just the slow part.

The whisper adapter now cuts long audio the same way the parakeet adapter does — reusing
`engines/chunking.py` rather than a second copy of the same cut-in-a-pause logic — but for a
different reason and with a much larger `CHUNK_SECONDS`: there is no VRAM ceiling forcing it down to
5 minutes, only the wish to keep any one whisper-cli call short enough to survive a CPU fallback and
to keep one bad chunk from costing the rest of the Meeting.

## Why not the alternatives

- **Just raise `TRANSCRIBE_TIMEOUT_SECONDS`.** This would not have helped the run that actually
  failed — the error was a non-zero exit, not a timeout — and it does nothing for the blast radius:
  one whisper-cli call still stands or falls as a unit for the entire Meeting.
- **Investigate and fix the GPU-detection flake instead.** Worth doing if it recurs, but it is a
  whisper.cpp/driver-level flake outside this codebase's control, and chunking is a cheap hedge
  against it (and against any other single-run failure) regardless of its root cause.
- **A whisper.cpp-specific chunk length copied from parakeet's 300s.** Nothing here is VRAM-bound, so
  there is no reason to cut this often. `CHUNK_SECONDS = 900` was picked to leave most real meetings
  uncut while keeping a worst-case CPU-fallback chunk well under the timeout; re-measure if that
  stops holding.

## Consequences

- `engines/chunking.py`'s `chunk_bounds` is now shared by both adapters; each keeps its own
  `CHUNK_SECONDS` and `MIN_TAIL_SECONDS`, tuned to its own constraint (VRAM for parakeet, wall-clock
  resilience for whisper).
- As with parakeet, a per-chunk failure fails the Job rather than producing a partial transcript.
- ADR-0003's claim that "whisper.cpp already windows internally and needs none of this" is superseded
  by this ADR: internal windowing solved whisper.cpp's VRAM problem, not its wall-clock one.
