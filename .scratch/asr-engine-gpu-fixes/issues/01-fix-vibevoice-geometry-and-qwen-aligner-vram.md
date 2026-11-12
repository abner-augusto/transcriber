# 01 - Fix VibeVoice Streaming Geometry and Qwen Aligner VRAM

**What to build:** Make the two Python Engines actually usable on the target
machine (Windows, RTX 5070 Ti 16 GB): VibeVoice must transcribe at the
checkpoint's audio rate and streaming geometry, Qwen3-ASR must stop approaching
the VRAM ceiling on a 300 s chunk, and the "the models are using CPU" symptom
must be explained from measurements rather than guessed at.

**Blocked by:** none.

**Status:** done

- [x] VibeVoice decodes audio at the checkpoint's `target_sample_rate` and passes `chunk_duration`/`text_audio_delay` derived from `chunk_frames`/`lookahead_frames`.
- [x] VibeVoice output on `test.mp3` is correct Portuguese instead of fluent nonsense.
- [x] VibeVoice control tokens (`[Music]`, `[Silence]`, `[Beep]`) never become Words.
- [x] Qwen3-ASR's forced aligner no longer materialises the math-SDPA score matrix over a whole 300 s chunk.
- [x] Qwen single-sample batches drop the redundant all-ones attention mask.
- [x] Attention backend choice is documented where it is scoped, with the measured reason.
- [x] Unit tests cover the frame-config contract, the mask drop, and control-token parsing.
- [x] ADR-0005 and `docs/engine-runtimes.md` record the corrections and the baseline comparison.

## Evidence

`test.mp3` (60 s, Brazilian Portuguese radio), RTX 5070 Ti 16 GB, desktop holding ~2.5-3 GB:

| Engine | Inference | RTF | Peak VRAM | Transcript |
|---|---|---|---|---|
| whisper.cpp large-v3-turbo (baseline) | 4.9 s | 12.3x | 4867 MiB | correct |
| faster-whisper large-v3 (baseline) | 12.3 s | 4.9x | 6794 MiB | correct |
| Qwen3-ASR 1.7B + aligner (fixed) | ~11 s / 60 s chunk | ~5.4x | 8966 MiB (was 9745) | correct |
| VibeVoice 7B NF4 (before) | ~30 s | ~2x | 11522 MiB | Catalan-looking gibberish |
| VibeVoice 7B NF4 (fixed) | ~30 s | ~2x | 9858 MiB | correct, 3-4 native turns |

Wall-clock in the table excludes process start and model load (~15 s Qwen3-ASR,
~30 s VibeVoice NF4). Measured with `--no-monitor`: polling `nvidia-smi` every
0.5 s from another process inflates a short decode by ~30% and must not be used
for timing.

Qwen3-ASR on a 300 s chunk: peak **15 624 MiB -> 8483 MiB**; aligner forward
~34 s (math, under allocator pressure) -> ~1-2 s.

Attention investigation: a decode step issues **2010 CUDA kernel launches**
(measured with `torch.profiler`); Flash-Attention is absent from the Windows
wheel and memory-efficient SDPA is runtime-disabled on sm_120, so SDPA uses math.
Forcing cuDNN globally is a trap: ~37 s of autotune per fresh process, and
VibeVoice streaming drops from 3.01x to 0.90x RTF. cuDNN is therefore scoped to
the Qwen aligner only.

**Verification:** `tests/test_engines.py` (44 passed) and the full suite
(236 passed, 20 skipped) plus the end-to-end runs above through the isolated
runtime protocol. Bench harnesses live in `.scratch/gpu-smoke/`
(`repro_engine.py`, `bench_baseline.py`, `qwen_*`, `vibevoice_timing.py`).
