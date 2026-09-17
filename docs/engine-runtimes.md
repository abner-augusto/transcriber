# Isolated Engine runtimes

Qwen3-ASR and VibeVoice use separate environments under `venv-engines/`. On
Windows their default interpreters are:

- `venv-engines/qwen3-asr/Scripts/python.exe`
- `venv-engines/vibevoice/Scripts/python.exe`

On Linux and macOS, set `QWEN3_ASR_PYTHON` and `VIBEVOICE_PYTHON` to the respective
`bin/python` paths. Run the metadata doctor from each interpreter after installing
its immutable requirement file. If its fingerprint changes or health reports
`runtime.executable` blocked, rebuild only that Engine environment.

Model-load and inference checks are opt-in because they load large local weights.
Run them sequentially; never keep both GPU Engines resident concurrently.

Runtime crashes, timeouts, malformed responses, and protocol version mismatches
fail the Job. Missing optional forced alignment remains a degraded result using
the proportional timestamp fallback.

## Measured on Windows + Blackwell (RTX 5070 Ti, sm_120)

Windows CUDA wheels ship without Flash-Attention, and PyTorch disables the
memory-efficient kernel at runtime on sm_120, so `scaled_dot_product_attention`
resolves to the math fallback unless a kernel is chosen explicitly. That
fallback is CPU-bound: ~2000 kernel launches per decode token on Qwen3-ASR, with
the GPU idling and the CPU saturated — the work is on the GPU's behalf, not
"CPU inference". Two consequences are encoded in the adapters:

- Qwen3-ASR keeps the default backend for token-by-token decoding (forcing cuDNN
  costs ~37 s of autotune in a fresh process and is no faster per token) but runs
  the forced aligner inside `engines/torch_attention.py::fused_attention_first`.
  On a 300 s chunk that took the aligner from 9.9 GB to 6.1 GB peak and the whole
  Job from a 15.6 GB near-OOM to ~8.5 GB.
- VibeVoice deliberately does not override the backends: its streaming decoder
  attends over one token against a short cache, where cuDNN is ~3x slower.

`drop_single_sample_padding_mask` removes the all-ones mask these Engines
generate for their single-sample batches; the mask encodes nothing but forces
SDPA away from fused kernels.

## VibeVoice streaming geometry

`preprocessor_config.json` is a contract, not a hint. The adapter decodes audio
at `target_sample_rate` (24 kHz) and passes `chunk_duration`/`text_audio_delay`
derived from `chunk_frames`/`lookahead_frames` (22 and 4 for
VibeVoice-ASR-Streaming-7B, i.e. 2.93 s and 0.53 s). Feeding 16 kHz audio with a
10 s chunk does not fail — it produces fluent text in the wrong language.
