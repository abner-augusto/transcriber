# 0007 - Primary Engines in daily use

**Status**: accepted

## Context

The tool supports five Transcriber Engines (whisper.cpp, faster-whisper,
parakeet.cpp, qwen3-asr, vibevoice) behind ten Presets. Each Engine costs a
health check, an installer path, smoke-test tiers, and adapter maintenance.
The 2026-09-24 architecture review suggested pruning Engines, and named
parakeet.cpp as a candidate because ADR-0005's benchmark recorded English
hallucinations from Parakeet-TDT 0.6B on Brazilian Portuguese.

Daily use says otherwise. On the user's real Meetings (Portuguese, with
names and technical terms), the Presets used most are:

1. **parakeet.cpp** (`parakeet-tdt-0.6b-v3` and siblings): fewest errors on
   names and technical terms in practice.
2. **faster-whisper `large-v3`** (the full model, not turbo).

qwen3-asr and whisper.cpp are used less. Of the two primaries, faster-whisper `large-v3` +
pyannote is the most stable end to end, so it is the **baseline** every comparison is measured
against (plan 021); parakeet.cpp is preferred when names and technical terms matter most. vibevoice is still being matured and
evaluated before it is trusted for real Meetings.

## Decision

- parakeet.cpp and faster-whisper `large-v3` are the **primary** Engines.
  They must keep working through every refactor and stack change.
- qwen3-asr and whisper.cpp are **secondary**: supported, not the reference
  for behavior or performance decisions.
- vibevoice is **experimental** until its evaluation is complete
  (`.scratch/architecture-review/issues/07-vibevoice-maturation.md`).
- Do not propose removing parakeet.cpp. Any Engine pruning needs a
  `bench/` comparison on the user's own recordings, not the ADR-0005 numbers
  alone.

## A fact to keep in mind

`engines/parakeet_cpp.py` **ignores Vocabulary** ("Parakeet takes no
prompt"). Parakeet's accuracy on names comes from the model itself, not from
the terms the user supplies. Vocabulary reaches faster-whisper
(`initial_prompt`), whisper.cpp (`--prompt`), qwen3-asr, and vibevoice only.
Making Vocabulary useful for Parakeet is tracked in
`.scratch/architecture-review/issues/06-vocabulary-for-parakeet.md`.

## Consequences

- Stack simplification (dropping Postgres/Redis/Celery/Docker) must keep the
  parakeet.cpp binary build and the faster-whisper package in the core
  install. faster-whisper also supplies the Silero VAD used by
  `services/vad_service.py`.
- Smoke tests and benchmarks should cover the primary Engines first.
- Architecture work that touches the Transcriber seam (for example, returning
  a `Transcription` value) is validated against parakeet.cpp and
  faster-whisper before the others.
