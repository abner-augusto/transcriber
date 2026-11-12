# Plan 021: Evaluate VibeVoice against the daily stack

> **Executor instructions**: Follow this plan step by step. Steps 3–4 run on
> the user's machine (GPU, private recordings). On a STOP condition, stop and
> report. When done, update `plans/README.md`,
> `.scratch/architecture-review/issues/07-vibevoice-maturation.md`, and
> ADR-0007.
>
> **Drift check (run first)**: `git diff --stat 6ee29ea..HEAD -- bench/ engines/vibevoice.py engine_runners/ tasks/diarization.py transcript/`

> **Local-only steps**: see "Run locally by the user" in `plans/README.md`. An agent
> stops before them, leaves their boxes unchecked, and never writes estimated numbers.

## Status

- **Priority**: P3
- **Effort**: M
- **Risk**: LOW (no product code changes unless the evaluation finds bugs)
- **Depends on**: plans 012/013 (done). Plan 015 simplifies step 2 but is
  not required.
- **Planned at**: commit `6ee29ea`, 2026-09-24
- **Source**: design session 2026-09-24 on ticket 07

## Decisions (do not re-litigate)

1. **Two separate axes.**
   - *Diarization*: fix the Words, swap only the Turns. Faster-whisper
     large-v3 Words + pyannote Turns vs the same Words + VibeVoice native
     Turns. Attribution depends on Word timestamps, so fixing the Words is
     what isolates the Diarizer. Repeat with VibeVoice's own Words as a
     second fixed set.
   - *Transcription*: parakeet.cpp, faster-whisper large-v3, and VibeVoice
     text, scored on overall WER and on Vocabulary terms (names, technical
     terms).
2. **Baseline** for every comparison: faster-whisper large-v3 + pyannote
   (the user's most stable stack; ADR-0007).
3. **Evaluation set**: 3–4 single-track Meet recordings with Gemini
   transcripts as speaker-labelled references, plus `arquitetura-03`:
   one with 2 people, one with 4+, one longer than 45 min. Dual-track
   Meetings are excluded (the dual-track path takes precedence over native
   Turns; plan 012).
4. **Metrics**: WER, Vocabulary-term accuracy, WDER **with coverage**
   (`bench/wder.py`), wall-clock per audio hour, peak VRAM.
5. **Promotion rule**:
   - *Primary Diarizer option* if VibeVoice Turns beat pyannote Turns on the
     fixed Words by ≥ 3 WDER points at similar coverage, on most recordings.
   - *Primary Transcriber* additionally needs Vocabulary-term accuracy no
     worse than the baseline and wall-clock ≤ 1× real time.
   - Better Speakers but worse names → *secondary, for hard-to-separate
     Meetings*. Neither → stays experimental with the numbers recorded.
6. **Privacy (ADR-0001)**: only numbers and manifests (paths) are committed.
   Transcripts and references stay outside the repo; the bench refuses to
   write text under `bench/results/`.

## Steps

1. **Manifests**: one manifest per recording under `bench/samples/<id>/`
   (paths only), following the existing `arquitetura-03` layout.
2. **Turn-swap scorer**: `bench/diarizer_swap.py` takes one Words source and
   two Turn sources (stored `raw_diarization` or a native Turns export), runs
   `derive_segments` for each (with `MeetingDiarization`, plan 012), and
   scores both with `bench/wder.py` against the reference. Unit-test it on a
   tiny synthetic reference.
3. **Transcription scorer**: WER and Vocabulary-term accuracy per Engine
   against the same references; the Vocabulary list per recording lives in
   its manifest.
4. **Run on the user's machine** for every recording and Engine; record
   wall-clock and peak VRAM (`nvidia-smi --query-gpu=memory.used` polling).
5. **Results**: `bench/results/<date>-<recording>.json` (numbers only) and
   `bench/results/vibevoice-evaluation.md` summarizing the promotion rule's
   outcome. Update ADR-0007 with the decision.

## Done criteria

- [ ] Both axes measured on every recording in the set
- [ ] No transcript text in the repository (`rg` over `bench/results/` for a known phrase returns nothing)
- [ ] ADR-0007 records promote / secondary / experimental with the numbers

## STOP conditions

- VibeVoice fails on a recording (OOM, garbage language — see the ADR-0005
  addendum). Record it as a finding and fix in a separate ticket; do not tune
  the evaluation around it.
- Coverage differs by more than 10 points between the two Turn sets on the
  same Words; WDER is then not comparable.
