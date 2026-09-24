# Plan 012: One Diarization stage for full processing and Reprocessing

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 6ddfd46..HEAD -- tasks/process_meeting.py tasks/reprocess_task.py tasks/dual_track.py tasks/shared.py services/vad_service.py services/speaker_id_service.py tests/test_pyannote_exclusive.py tests/test_dual_track.py tests/test_task_failure_lifecycle.py tests/fakes.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Supersedes**: `plans/008-rediarize-dual-track-meetings.md` (its bug fix and
  test plan are folded into this plan; do not execute 008 separately)
- **Category**: bug + architecture (deepening)
- **Planned at**: commit `6ddfd46`, 2026-09-24
- **Source**: architecture review 2026-09-24, candidate 1
  (`.scratch/architecture-review/README.md`)

## Why this matters

The three ways a Meeting gets its Turns — single-track (Diarizer + VAD mask),
dual-track (mic VAD → `HOST`, Diarizer on the system track), and native
(VibeVoice Turns) — are written inline in `process_meeting_task`.
Reprocessing copied only the single-track path, so re-diarizing a dual-track
Meeting runs the Diarizer over the mixed file and loses the host/remote split,
and re-identify never passes `host_label`, so the host stops being named
"You". `raw_diarization` is written in three places with two shapes, and the
"exclusive Turns if any, else Turns" rule is copied into both tasks.

After this plan there is one Diarization stage module with a small interface.
Both tasks call it, the stored shape lives in one type, and the dual-track
Reprocessing bug is fixed because there is no second copy to drift.

## Current state

- `tasks/process_meeting.py:104-164` — Step 3. Dual-track branch (106-142):
  mic VAD → `host_turns_from_vad`; `diarizer.diarize(system_path)`; VAD mask on
  the system track; `build_dual_diarization`; writes `raw_diarization` with
  `engine`, `turns`, `exclusive_turns`, `overlaps`, `host_label` (no
  `original_*` keys). Single-track branch (143-163): native Turns via
  `transcriber.get_native_diarization()` when `has_native_diarization`, else
  `diarizer.diarize(audio_path)`; then `prepare_diarization`; writes
  `{"engine": ..., **diarization_data}`.
- `tasks/process_meeting.py:173-190` — picks `attribution_turns`
  (exclusive if non-empty, else bounded), `speaker_labels` from
  bounded + exclusive, `host_label` only when dual-track.
- `tasks/reprocess_task.py:35-60` — always `diarizer.diarize(audio_path)` +
  `prepare_diarization`; no `is_dual_track` check. Lines 57-60 read stored
  Turns via `turns_from_stored` / `exclusive_turns_from_stored`.
- `tasks/reprocess_task.py:64-90` — same attribution-turn and label logic,
  `name_speakers` **without** `host_label`.
- `tasks/shared.py` — `prepare_diarization` (VAD bound + `original_*` keys),
  `turns_from_stored`, `exclusive_turns_from_stored`,
  `attribution_turns_from_stored` (unused by tasks), `overlaps_from_stored`
  (used by `models/meeting.py:72`).
- `tasks/dual_track.py` — `HOST_SPEAKER`, `host_turns_from_vad`,
  `build_dual_diarization`. Pure, tested in `tests/test_dual_track.py`.
- `services/audio_service.py` — `DUAL_MIC_OUTPUT = "mic_processed.wav"`,
  `DUAL_SYSTEM_OUTPUT = "system_processed.wav"`.
- `tests/test_pyannote_exclusive.py:268+` — process + rediarize + reidentify
  harness with `FakeTranscriber` / `FakeDiarizer` from `tests/fakes.py`.
  Copy this style.

Domain vocabulary (`CONTEXT.md`): a **Diarizer** produces **Turns**; the
**Speaker Namer** names Speakers; **Reprocessing** re-runs diarization or
naming without transcribing again.

## Target interface

Create a new pure package `transcript/` (no DB, no Redis, no config import):

```python
# transcript/__init__.py  — empty docstring module
# transcript/diarization.py
@dataclass(frozen=True)
class MeetingDiarization:
    """Everything a Meeting knows about who spoke when, in one stored shape."""
    engine: str
    turns: list[Turn]                      # VAD-bounded Turns
    exclusive_turns: list[Turn] | None
    overlaps: list[dict]
    host_label: str | None = None          # dual-track only
    original_turns: list[Turn] | None = None
    original_exclusive_turns: list[Turn] | None = None
    original_overlaps: list[dict] | None = None

    @property
    def attribution_turns(self) -> list[Turn]: ...   # exclusive if non-empty, else turns
    @property
    def speaker_labels(self) -> list[str]: ...       # sorted labels over turns + exclusive
    def to_stored(self) -> dict: ...
    @classmethod
    def from_stored(cls, raw) -> "MeetingDiarization | None": ...  # None for empty; accepts legacy bare list
```

And the stage itself in `tasks/diarization.py` (it touches files and Engines,
so it stays in `tasks/`):

```python
def diarize_meeting(
    meeting,                 # needs .id, .is_dual_track, .min_speakers, .max_speakers
    audio_path: str,
    *,
    diarizer,
    vad_service,
    native: DiarizationResult | None = None,
    native_engine: str | None = None,
) -> MeetingDiarization:
    """Dual-track → host/remote path. Else native Turns if given. Else the Diarizer."""
```

Rules:

- Dual-track wins over native. A dual-track Meeting always uses the host/remote
  path (same as today: the dual branch is checked first).
- `to_stored()` must reproduce today's key sets exactly: dual-track writes
  `engine, turns, exclusive_turns, overlaps, host_label`; single-track and
  native write `engine` plus the six keys `prepare_diarization` returns.
  Omit `host_label` and the `original_*` keys when they are `None` rather than
  writing nulls, so stored JSON stays byte-compatible with existing Meetings.
- `from_stored()` must read every shape currently on disk: the dual dict, the
  single dict, a dict without `exclusive_turns`, and the legacy bare list.
  When `overlaps` is missing, compute it with `compute_overlaps(turns)` (what
  `overlaps_from_stored` does today).
- Re-diarize never uses native Turns (product rule carried over from plan 008):
  `rediarize_task` calls `diarize_meeting` with `native=None`.
- The stage does not persist and does not unload models. Tasks assign
  `meeting.raw_diarization = result.to_stored()` and keep their existing
  `unload` / `release_gpu_memory` calls (unchanged until backlog ticket 04).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| New stage tests | `.\venv\Scripts\python.exe -m pytest tests/test_diarization_stage.py -q` | all pass |
| New Reprocessing tests | `.\venv\Scripts\python.exe -m pytest tests/test_reprocess_dual_track.py -q` | all pass |
| Related task tests | `.\venv\Scripts\python.exe -m pytest tests/test_pyannote_exclusive.py tests/test_task_failure_lifecycle.py tests/test_dual_track.py tests/test_gpu_memory.py -q` | all pass |
| Ordinary backend suite | `.\venv\Scripts\python.exe -m pytest -m "not model_load and not model_inference" -q` | exit 0 |
| Diff whitespace | `git diff --check` | exit 0 |

(On Linux/macOS use `venv/bin/python`.)

## Scope

**In scope**:

- `transcript/__init__.py`, `transcript/diarization.py` (create)
- `tasks/diarization.py` (create)
- `tasks/process_meeting.py` (Step 3 and the label / attribution-turn lines of
  Steps 4-5 only)
- `tasks/reprocess_task.py`
- `tasks/shared.py` (remove `prepare_diarization` once it moves; keep
  `turns_from_stored` and the other stored readers for plan 013)
- `tests/test_diarization_stage.py`, `tests/test_reprocess_dual_track.py` (create)

**Out of scope**:

- Splitting `tasks/shared.py` beyond `prepare_diarization` (plan 013).
- `models/meeting.py` (plan 013 switches its import).
- The Transcriber port / `has_native_diarization` probing (backlog ticket 01).
- `engines/`, `engine_runtimes/`, frontend, API routes.
- GPU unload / residency changes.

## Git workflow

- Branch: the session's designated branch, or `advisor/012-diarization-stage`
- Commits, in order:
  1. `test: pin raw_diarization shapes and dual-track rediarize bug`
  2. `refactor(transcript): add MeetingDiarization record`
  3. `refactor(tasks): route diarization through one stage`
  4. `fix(tasks): rediarize and reidentify dual-track Meetings via host path`
- Do NOT push unless instructed.

## Steps

### Step 1: Characterization tests first

Create `tests/test_diarization_stage.py` that runs **today's**
`process_meeting_task` (harness from `tests/test_pyannote_exclusive.py:268+`)
three times — single-track, native (a `FakeTranscriber` subclass with
`has_native_diarization = True` and `get_native_diarization()`), and
dual-track — and snapshots `meeting.raw_diarization` for each into literal
expected dicts in the test. For dual-track, monkeypatch
`tasks.process_meeting.get_meeting_path` / `config.get_meeting_path` to
`tmp_path / meeting.id`, create empty `mic_processed.wav` /
`system_processed.wav`, stub `AudioService.extract_dual_audio`, and give the
fake VAD different regions per path (mic → `[(0.0, 1.0)]`, system →
`[(0.5, 1.5)]`).

Create `tests/test_reprocess_dual_track.py` from plan 008 Step 1: a
dual-track Meeting with stored Words; `rediarize_task` must call
`diarize` with a path ending in `system_processed.wav`, stored
`raw_diarization["host_label"] == "HOST"`, and one Speaker has
`identified_by == "host_track"`. A second test: `reidentify_task` on a
dual-track Meeting keeps `"You"`. A third: missing processed tracks →
Job FAILED with a message naming the missing file. A fourth: a single-track
Meeting still diarizes `audio_filepath`.

**Verify**: stage snapshots pass on current code; the dual-track Reprocessing
tests **fail** on current code (that is the bug).

### Step 2: Add `MeetingDiarization`

Implement `transcript/diarization.py` per "Target interface". Unit-test
`to_stored` / `from_stored` round-trips against the three snapshots from
step 1, the legacy bare list, a dict without `exclusive_turns`, and a dict
without `overlaps`. Test `attribution_turns` (empty exclusive list falls back
to `turns`) and `speaker_labels`.

Move `prepare_diarization`'s body into a private helper of
`tasks/diarization.py` (it needs `vad_service`); `transcript/` must not import
`services/` or `config`.

**Verify**: `.\venv\Scripts\python.exe -m pytest tests/test_diarization_stage.py -q` → all pass.

### Step 3: Implement `diarize_meeting` and switch `process_meeting_task`

- Dual-track: mic/system paths from `get_meeting_path(meeting.id)`; raise
  `RuntimeError` naming the missing file if either is absent; host Turns from
  mic VAD; Diarizer on the system track; VAD mask; `build_dual_diarization`;
  `engine=DIARIZER_ENGINE`, `host_label=HOST_SPEAKER`.
- Native: bound through the moved `prepare_diarization` logic,
  `engine=native_engine`.
- Otherwise: `diarizer.diarize(audio_path, min_speakers=..., max_speakers=...)`
  then the same bounding, `engine=DIARIZER_ENGINE`.

In `process_meeting_task`, Step 3 becomes: pick `native` / `native_engine`
from the transcriber exactly as today, call `diarize_meeting`, set
`meeting.raw_diarization = diarization.to_stored()`. Keep the progress
messages and percentages (50 / 70) — use the dual-track message when
`meeting.is_dual_track`, the native message when native, else the Diarizer
message. Steps 4-5 use `diarization.attribution_turns`,
`diarization.speaker_labels`, `diarization.turns`, and
`host_label=diarization.host_label`.

**Verify**: step 1 snapshots still pass unchanged.

### Step 4: Switch Reprocessing

`_reprocess_meeting`:

- `rerun_diarization=True` → `diarize_meeting(meeting, audio_path, diarizer=..., vad_service=VadService())`
  (no `native`), then persist `to_stored()`.
- `rerun_diarization=False` → `MeetingDiarization.from_stored(meeting.raw_diarization)`;
  raise the existing "No existing diarization found" error when `None` or no
  Turns.
- Both paths: `attribution_turns`, `speaker_labels`, and
  `name_speakers(..., host_label=diarization.host_label)`.

For a dual-track Meeting whose stored `raw_diarization` predates `host_label`
(it always had it since dual-track shipped — verify with `git log -S host_label`),
`from_stored` returns `host_label=None`; that is acceptable.

**Verify**: `.\venv\Scripts\python.exe -m pytest tests/test_reprocess_dual_track.py tests/test_diarization_stage.py tests/test_pyannote_exclusive.py tests/test_task_failure_lifecycle.py tests/test_dual_track.py -q` → all pass.

### Step 5: Delete what the stage replaced

- Remove the now-unused imports in both tasks (`prepare_diarization`,
  `turns_from_stored`, `exclusive_turns_from_stored`, `build_dual_diarization`,
  `host_turns_from_vad`, `DUAL_*` constants, `HOST_SPEAKER` where unused).
- Remove `prepare_diarization` from `tasks/shared.py` if nothing imports it
  (update `tests/test_pyannote_exclusive.py` imports if they do).
- Leave `turns_from_stored`, `exclusive_turns_from_stored`,
  `attribution_turns_from_stored`, `overlaps_from_stored` for plan 013.

**Verify**: ordinary backend suite exits 0; `git diff --check` exits 0.

## Test plan

- `tests/test_diarization_stage.py` — stored-shape snapshots for single,
  native, dual; `MeetingDiarization` round-trips incl. legacy shapes;
  `attribution_turns` / `speaker_labels`; `diarize_meeting` dispatch
  (dual beats native; native bypasses the Diarizer; single calls the Diarizer
  with `min/max_speakers`).
- `tests/test_reprocess_dual_track.py` — the four cases from step 1.
- No GPU or model tests. Fakes only.

## Done criteria

- [ ] All commands in "Commands you will need" pass
- [ ] `rg "diarize_meeting" tasks/process_meeting.py tasks/reprocess_task.py` matches both
- [ ] `rg "raw_diarization = \{" tasks` returns nothing (all writes go through `to_stored()`)
- [ ] `rg "host_label" tasks/reprocess_task.py` matches the `name_speakers` call
- [ ] `transcript/` imports nothing from `tasks`, `services`, `config`, `database`, or `redis`
- [ ] Step 1 snapshots pass unmodified at the end
- [ ] `plans/README.md` rows for 012 (DONE) and 008 (superseded) are correct

## STOP conditions

- Current-state excerpts no longer match.
- A snapshot in step 1 can only be made to pass after step 3 by editing the
  expected dict. That means stored JSON changed shape; report the diff instead.
- The frontend or an API route reads a `raw_diarization` key you would drop
  (`rg raw_diarization frontend/src api` should show only the existence check
  in `api/meetings.py`).
- You think re-diarize should use VibeVoice native Turns. It must not.
- You need to change `engines/` or the Transcriber port.

## Maintenance notes

- `MeetingDiarization` is the seam plan 013 builds on: the Segment derivation
  module takes one, not raw Turn lists.
- When backlog ticket 01 (Transcriber returns a `Transcription`) lands,
  `native` / `native_engine` collapse into one argument taken from the
  `Transcription`.
- Backlog ticket 04 (per-Job child process) will remove the unload calls around this
  stage; do not move them into the stage now.
