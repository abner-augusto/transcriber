# Plan 013: Move Segment derivation out of `tasks/shared.py`

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat <commit that finished plan 012>..HEAD -- tasks/shared.py tasks/process_meeting.py tasks/reprocess_task.py transcript/ models/meeting.py tests/test_build_segments.py tests/test_pyannote_exclusive.py tests/test_vad_service.py`
> If any in-scope file changed since plan 012 landed, compare the "Current
> state" excerpts against the live code before proceeding; on a mismatch,
> treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: `plans/012-deepen-diarization-stage.md`
- **Category**: architecture (deepening)
- **Planned at**: commit `6ddfd46`, 2026-09-24 (re-check line numbers after 012)
- **Source**: architecture review 2026-09-24, candidate 3
  (`.scratch/architecture-review/README.md`)

## Outcome (2026-09-24)

Done in `8581398`, as one commit instead of two because deleting the stored
readers and switching `models/meeting.py` had to land together. An AST
comparison confirmed every moved definition is unchanged; `derive_segments`
is the only new code.

## Why this matters

The most-changed domain logic in the repo — Word-to-Speaker attribution
(Viterbi smoothing over Turn evidence) and Segment breaking — lives in
`tasks/shared.py` next to a module-level Redis connection pool, the Job
lifecycle context manager, progress publishing, and DB persistence.
Importing `build_segments` therefore imports Redis, `config`, and `database`.
`models/meeting.py` imports `overlaps_from_stored` from `tasks`, so the model
layer depends on the task layer. All the speaker-attribution-precision work
(`.scratch/speaker-attribution-precision/`) lands in this code.

After this plan, Segment derivation is a pure module in `transcript/` with
one entry point that takes a `MeetingDiarization` (from plan 012), and
`tasks/shared.py` holds only Job lifecycle and persistence.

## Current state (at `6ddfd46`; plan 012 changes the callers)

- `tasks/shared.py:1-40` — imports `redis`, `celery`, `config`, `database`,
  `models`; creates `_redis_pool` at import time; defines
  `SENTENCE_ENDINGS`, `MAX_PAUSE_SECONDS`, `MAX_SEGMENT_SECONDS`,
  `NEAREST_TURN_TOLERANCE_SECONDS`, `SPEAKER_SWITCH_PENALTY`,
  `UNKNOWN_SPEAKER`.
- `tasks/shared.py:41-80` — `_TurnIndex` (interval tree for nearby Turns).
- `tasks/shared.py:~250-470` — `smooth_word_speakers`, `_candidate_emission`,
  `_alignment_weight`, `build_segments`, `_breaks_before`, `_close`.
- `tasks/shared.py:~470-565` — `words_from_stored`, `turns_from_stored`,
  `exclusive_turns_from_stored`, `attribution_turns_from_stored`,
  `overlaps_from_stored` (after 012, the Turn readers duplicate
  `MeetingDiarization.from_stored`).
- `models/meeting.py:72-73` — `from tasks.shared import overlaps_from_stored`.
- Importers in tests: `tests/test_build_segments.py:8-17`,
  `tests/test_vad_service.py:8`, `tests/test_pyannote_exclusive.py:12-17`.
- `preferences.py:7` duplicates the 0.8 default as
  `DEFAULT_SPEAKER_SWITCH_PENALTY`.

## Target interface

```python
# transcript/segments.py
def derive_segments(
    words: list[Word],
    diarization: MeetingDiarization | None,
    switch_penalty: float = SPEAKER_SWITCH_PENALTY,
) -> list[dict]:
    """The Segments a reader sees: Words attributed to Speakers, then broken
    at speaker changes, sentence ends, long pauses, and length limits."""
```

`build_segments(words, turns, switch_penalty)` and `smooth_word_speakers`
stay public in the same module as internal seams for the existing
attribution tests; `derive_segments` is the entry point the tasks use, and
it owns the choice of `diarization.attribution_turns`. `None` diarization
means every Word is `UNKNOWN` (current behavior with no Turns).

`words_from_stored` moves to `transcript/words.py` (pure; reads a
`raw_transcription` of any era).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Segment tests | `.\venv\Scripts\python.exe -m pytest tests/test_build_segments.py tests/test_vad_service.py tests/test_pyannote_exclusive.py -q` | all pass |
| Purity check | `.\venv\Scripts\python.exe -c "import sys, transcript.segments; bad=[m for m in ('redis','celery','database','config','sqlalchemy') if m in sys.modules]; print(bad); raise SystemExit(bool(bad))"` | prints `[]`, exit 0 |
| Ordinary backend suite | `.\venv\Scripts\python.exe -m pytest -m "not model_load and not model_inference" -q` | exit 0 |
| Diff whitespace | `git diff --check` | exit 0 |

## Scope

**In scope**:

- `transcript/segments.py`, `transcript/words.py` (create)
- `transcript/diarization.py` (only if `overlaps` fallback needs a helper)
- `tasks/shared.py` (delete moved code)
- `tasks/process_meeting.py`, `tasks/reprocess_task.py` (imports and the
  `derive_segments` call)
- `models/meeting.py` (read overlaps via `MeetingDiarization.from_stored`)
- `preferences.py` (import the default penalty from `transcript.segments`
  instead of repeating 0.8)
- Test files that import the moved names

**Out of scope**:

- Any change to attribution behavior, constants, or Segment breaking rules.
- `rebuild_speakers_and_segments`, `meeting_job`, `update_progress`,
  `publish_event` (they move with the Job module ticket, not here).
- Engines, API, frontend.

## Git workflow

- Commits: `refactor(transcript): move Segment derivation out of tasks` then
  `refactor(models): read overlaps without importing tasks`
- Do NOT push unless instructed.

## Steps

### Step 1: Move the code verbatim

Cut constants, `_TurnIndex`, `smooth_word_speakers`, `_candidate_emission`,
`_alignment_weight`, `build_segments`, `_breaks_before`, `_close` into
`transcript/segments.py` with no edits except imports. Move `words_from_stored`
to `transcript/words.py`. Do not leave re-exports in `tasks/shared.py`; update
every importer instead (`rg "from tasks.shared import" tests tasks models`).

**Verify**: segment tests pass; purity check prints `[]`.

### Step 2: Add `derive_segments` and switch the tasks

Implement `derive_segments` as a thin wrapper over `build_segments` with
`diarization.attribution_turns`. Replace the `build_segments(...,
diarization.attribution_turns, ...)` calls in both tasks with
`derive_segments(words, diarization, switch_penalty=...)`. Add tests in
`tests/test_build_segments.py` that `derive_segments` prefers non-empty
exclusive Turns and falls back to Turns, and returns `UNKNOWN` Segments for
`None`.

**Verify**: ordinary backend suite exits 0.

### Step 3: Remove the stored-Turn readers and the models → tasks import

- `models/meeting.py`: replace `overlaps_from_stored(self.raw_diarization)`
  with `MeetingDiarization.from_stored(self.raw_diarization)` →
  `.overlaps` (empty list when `None`). Import from `transcript.diarization`.
- Delete `turns_from_stored`, `exclusive_turns_from_stored`,
  `attribution_turns_from_stored`, `overlaps_from_stored` from
  `tasks/shared.py`. Port their tests in `tests/test_build_segments.py` and
  `tests/test_pyannote_exclusive.py` to `MeetingDiarization.from_stored`
  assertions (same inputs, same expected Turns / overlaps).
- `preferences.py`: `from transcript.segments import SPEAKER_SWITCH_PENALTY as DEFAULT_SPEAKER_SWITCH_PENALTY`.

**Verify**: `rg "tasks" models/` returns nothing; ordinary suite exits 0;
`git diff --check` exits 0.

## Done criteria

- [ ] All commands in "Commands you will need" pass
- [ ] `tasks/shared.py` contains no attribution, Segment-breaking, or stored-reader code
- [ ] `rg "from tasks" models/` returns nothing
- [ ] No behavior change: every pre-existing assertion in `tests/test_build_segments.py` still holds (only imports and reader calls changed)
- [ ] `plans/README.md` status row for 013 updated

## STOP conditions

- Plan 012 has not landed (`transcript/diarization.py` missing).
- Moving the code requires changing any constant or branch in the
  attribution logic.
- A ported stored-reader test needs a different expected value.

## Maintenance notes

- Future attribution work (`.scratch/speaker-attribution-precision/`)
  should target `transcript/segments.py` and test through `derive_segments`
  where possible, `build_segments` / `smooth_word_speakers` only for
  Viterbi-level cases.
- After this plan, `tasks/shared.py` is the natural starting point for the
  Job module ticket (`.scratch/architecture-review/issues/02-job-module.md`).
