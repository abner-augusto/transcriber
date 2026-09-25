# 04 - Run Each Job in a Child Process

**Source:** architecture review 2026-09-24, candidate 6.

**What to build:** Run the whole pipeline for one Job in a child process that
exits when the Job ends, so the OS frees all GPU and host memory. Extends the
ADR-0006 subprocess pattern from two Engines to the pipeline.

**Why:** Models are class-level singletons in a long-lived worker
(`PyannoteDiarizer._pipeline`, `MMSCTCAligner`, `EmbeddingService._model`,
faster-whisper cache). Freeing VRAM depends on a hard-coded list in
`engines/gpu_memory.py::unload_all_engines` plus eleven manual
`unload`/`release_gpu_memory` calls in `tasks/`. A new adapter someone forgets
to register holds VRAM until the worker restarts. A native crash (CUDA, ffmpeg
binding) takes the worker down.

**Blocked by:** Plan 018's user data migration confirmation and the local
model-load measurements in Plan 019 Step 1. Plan 017 (issue 02) is complete.

**Status:** blocked (user-only prerequisites)

**Plan:** `plans/019-local-job-runner.md` (one Python process, child process per Job,
progress over a queue, timeout = max(60 min, 3× audio), PENDING Jobs resume on restart).

**Open questions for the exploration session:**
- `ProcessPoolExecutor(max_workers=1, max_tasks_per_child=1)` vs an explicit
  `subprocess` with a JSON handoff like ADR-0006?
- Measure model-load cost per Job for the primary Engines (ADR-0007):
  parakeet.cpp is already a subprocess; faster-whisper large-v3 and pyannote
  load times decide whether this is acceptable.
- Windows `spawn` start method: what must be importable and picklable?

**Acceptance criteria (draft):**
- [ ] `engines/gpu_memory.py` and every `unload()` call in `tasks/` are deleted
- [ ] A Job that crashes natively marks the Job FAILED and leaves the server running
- [ ] Measured VRAM after a Job returns to the idle baseline
