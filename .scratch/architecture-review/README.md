# Architecture review — 2026-09-24

Review run with the `improve-codebase-architecture` skill
(mattpocock/skills) against commit `6ddfd46`. Visual report (private
artifact, owner access): https://claude.ai/artifact/J7mR7gu5Ft3sJGF3zSebLZ

Vocabulary: **module, interface, depth, seam, adapter, leverage, locality**
as defined by the `codebase-design` skill; domain terms from `CONTEXT.md`.

## Decided

| Candidate | Where it lives | Status |
|-----------|----------------|--------|
| 1. Deepen the Diarization stage | `plans/012-deepen-diarization-stage.md` (supersedes plan 008) | done |
| 3. Move Segment derivation out of `tasks/shared.py` | `plans/013-extract-segment-derivation.md` | done |
| Primary Engines (parakeet.cpp, faster-whisper large-v3) | `docs/adr/0007-primary-engines-in-daily-use.md` | accepted |

## Backlog — each needs its own exploration session

Status `needs-exploration`: the direction is agreed, the interface is not.
Start a session by reading the ticket, then run the skill's grilling loop
(constraints, dependencies, shape of the deepened module, what sits behind
the seam, which tests survive). Turn the outcome into a `plans/NNN-*.md` and
flip the ticket to `ready-for-agent`.

| Ticket | Candidate | Blocked by |
|--------|-----------|------------|
| `issues/01-transcriber-returns-transcription.md` | 2 | ready → `plans/015-transcriber-returns-transcription.md` |
| `issues/02-job-module.md` | 4 | ready → `plans/017-job-module.md` |
| `issues/03-run-config.md` | 5 | ready → `plans/016-one-place-for-preferences-and-run-config.md` |
| `issues/04-per-job-child-process.md` | 6 | ready → `plans/019-local-job-runner.md` |
| `issues/05-stack-simplification.md` | stack | ready → `plans/018-sqlite-and-migration.md`, `plans/020-remove-legacy-infrastructure.md` |
| `issues/06-vocabulary-for-parakeet.md` | new (ADR-0007) | ready → `plans/014-vocabulary-correction.md` |
| `issues/07-vibevoice-maturation.md` | new (ADR-0007) | ready → `plans/021-vibevoice-evaluation.md` |
| `issues/08-correction-suggestions-ui.md` | from 06 | plan 014 |
| `issues/09-cancel-job.md` | from 02/04/05 | plan 019 |

## Explicitly rejected

- **Rewriting the backend in another language** (Go, Rust, Node). Diarizer,
  Voice Profiles, forced alignment, faster-whisper, Qwen3-ASR, and VibeVoice
  are PyTorch/Python; a new orchestrator language adds a second runtime and a
  subprocess per in-process Engine for no user-visible gain.
- **Removing parakeet.cpp.** See ADR-0007.
