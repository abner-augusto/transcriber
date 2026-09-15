# 0005 - Qwen3-ASR and VibeVoice Engines

**Status**: accepted

## Context

The system previously supported `whisper.cpp`, `parakeet.cpp`, and `faster-whisper` for transcription, coupled with `pyannote` for speaker diarization.

Benchmarks on Brazilian Portuguese meeting recordings (`2026-08-18 Reuniao Arquitetura 03 (pre legal).mov`) revealed two key opportunities:

1. **Vocabulary precision and elimination of English hallucinations**:
   Parakeet-TDT 0.6B suffered from 12 English word hallucinations (`you`, `what`, `yes`, `tell`, `view`, etc.) during Portuguese speech and failed on critical names (transcribing *"Garrah"* as *"Galo"*). By contrast, **Qwen3-ASR-1.7B** achieved zero English hallucinations and, via its prompt/hotwords capability, correctly transcribed Portuguese domain vocabulary and proper names.

2. **Native End-to-End Speaker Diarization**:
   PyAnnote community-1 achieved ~14.2% WDER with word/turn alignment challenges. By contrast, **VibeVoice-ASR-Streaming-7B** performs unified transcription and speaker attribution in a single neural pass, achieving **0.56% adjusted WDER (99.44% diarization accuracy)**.

## Decision

We introduce two new Engines into the interchangeable engine architecture:

### 1. `qwen3-asr` (Transcriber with Forced Alignment)
- Implemented in `engines/qwen3_asr.py` and registered as a standard `Transcriber`.
- Transcribes using `Qwen3-ASR-1.7B-hf` with sliding window chunking (300s window, 30s overlap) and sequence-matched stitching.
- Injects user vocabulary as domain hotwords (`prompt=vocabulary`).
- Obtains millisecond-accurate `Word` timestamps via `Qwen3-ForcedAligner-0.6B-hf` (with proportional fallback).
- Followed by external diarization (PyAnnote) and speaker naming, identical to Parakeet and Whisper.

### 2. `vibevoice` (Transcriber with Native Diarization)
- Implemented in `engines/vibevoice.py`.
- Transcribes using `VibeVoice-ASR-Streaming-7B` with 10-minute sliding windows and 45s overlap speaker voting.
- Loads the complete model with 4-bit NF4 weights and bfloat16 computation. Full bfloat16 weights exceed the safe VRAM budget on the target 16 GB GPU.
- Emits standard `Word` objects with timestamps via forced alignment.
- Exposes `has_native_diarization = True` and provides a native `DiarizationResult` (`Turn` objects for each speaker segment).
- In `tasks/process_meeting.py`, when a Transcriber provides native diarization, the pipeline uses the native `DiarizationResult` directly, bypassing PyAnnote and saving significant inference time and VRAM.

## Consequences

- **Extensibility**: Presets `qwen3-asr-1.7b.json` and `vibevoice-7b.json` allow users to select either model from the standard preset selector.
- **Port Contract Compliance**: Both adapters strictly satisfy `Transcriber` (emitting `Word` objects with leading space and timestamps).
- **VRAM Safety**: Both engines run one at a time and chunk long audio internally. VibeVoice requires NF4 quantization: the 36-minute benchmark peaked at about 6.94 GB allocated and 7.60 GB reserved, while full bfloat16 inference reached 15.88 GB on the 16 GB target GPU.
- **Diarization Flexibility**: Meetings using `qwen3-asr` continue to use PyAnnote; meetings using `vibevoice` get native end-to-end speaker attribution without running an external diarizer.
