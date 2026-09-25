# 0009 - Selectable Diarizer Engine

**Status**: accepted

## Context

The Diarizer is independent of the Meeting's Transcriber and its Preset.
Bench comparisons held Words fixed and found fewer speaker-attribution errors
with NVIDIA Nemotron 3 Diarization than pyannote Community-1:

| Meeting | pyannote WDER | Nemotron WDER |
|---|---:|---:|
| Arquitetura 03 (single track, 4 speakers, 36 min) | 1.60% | 0.73% |
| Sinop 2026-09-22 (dual track, 65 min) | 2.80% | 2.08% |

## Decision

- The selected Diarizer Engine is a Preference captured in each Job's RunConfig.
  `pyannote` remains the default; `nemotron-3-diarization` is opt-in.
- Nemotron runs in a dedicated Python runtime and receives local audio/model
  paths through protocol v1's `diarize` operation. Its model snapshot is
  installed locally; a Job never downloads weights.
- Nemotron uses Transformers commit
  `11c16613d93911300c38ec8c9c2460567be53281`, because no release available at
  adoption exposes `nemotron3_diarization`. Replace the pin with the first
  release that includes the model.
- The runner uses offline model loading and a default speaker threshold of
  0.5. Speakers with less than five seconds of total speech are removed.

## Consequences

Machines selecting Nemotron need its isolated runtime, local model snapshot,
FFmpeg, and a CUDA-capable device for the validated configuration. Runtime
failures fail the Job; the application does not silently switch Engines.
