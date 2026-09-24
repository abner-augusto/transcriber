# Plan 008: Re-diarize dual-track Meetings through the same host/remote path

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 40b455a..HEAD -- tasks/process_meeting.py tasks/reprocess_task.py tasks/dual_track.py tasks/shared.py services/audio_service.py services/speaker_id_service.py tests/test_dual_track.py tests/test_pyannote_exclusive.py tests/test_task_failure_lifecycle.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `40b455a`, 2026-09-17
- **Superseded by**: `plans/012-deepen-diarization-stage.md` (2026-09-24). Do not execute this plan.

## Why this matters

A dual-track Meeting attributes the local mic deterministically (`HOST`) and
runs the Diarizer only on the system track. Full processing implements that
in `process_meeting_task`. Re-diarize does not: it always calls
`diarizer.diarize(meeting.audio_filepath)` on the mixed file and never
passes `host_label` into the Speaker Namer. Re-diarizing an OBS/mic+system
Meeting therefore throws away the host/remote split the first run produced.

## Current state

- `tasks/process_meeting.py:97-133` — dual-track branch: VAD on
  `mic_processed.wav` → `host_turns_from_vad`; Diarizer + VAD mask on
  `system_processed.wav`; `build_dual_diarization`; stores `host_label`.
- `tasks/process_meeting.py:134-154` — single-track: native diarization if
  the Transcriber advertises it, else pyannote + `prepare_diarization`.
- `tasks/process_meeting.py:172-174` — `name_speakers(..., host_label=HOST_SPEAKER)`
  only when `meeting.is_dual_track`.
- `tasks/reprocess_task.py:35-50` — always `diarizer.diarize(audio_path)` +
  `prepare_diarization`. No `is_dual_track` check.
- `tasks/reprocess_task.py:84-86` — `name_speakers` without `host_label`.
- `tasks/dual_track.py` — `HOST_SPEAKER = "HOST"`, `host_turns_from_vad`,
  `build_dual_diarization`. Pure helpers, well tested.
- `services/audio_service.py:8-9` — `DUAL_MIC_OUTPUT = "mic_processed.wav"`,
  `DUAL_SYSTEM_OUTPUT = "system_processed.wav"`.
- `services/speaker_id_service.py:43-58` — `host_label` is named `"You"`
  with `identified_by: "host_track"` and skipped in voice-profile matching.
- `tests/test_dual_track.py` — unit tests for turn merge; no task-level
  rediarize coverage.
- `tests/test_pyannote_exclusive.py:268+` — process + rediarize with fakes
  for **single-track**. Copy this task-harness style.

Domain vocabulary from `CONTEXT.md`: **Turn** is what a Diarizer produces;
**Speaker Namer** assigns names; dual-track host is still a Speaker inside
the Meeting, labeled `HOST` then named `"You"`. **Reprocessing** re-runs
diarization without transcribing again.

Excerpts:

```python
# tasks/reprocess_task.py:35-50 (the bug)
if rerun_diarization:
    diarizer = make_diarizer()
    ...
    diar_result = diarizer.diarize(
        audio_path,
        min_speakers=meeting.min_speakers,
        max_speakers=meeting.max_speakers,
    )
    vad_service = VadService()
    diarization_data, bounded_turns, bounded_exclusive_turns = prepare_diarization(
        diar_result, audio_path, vad_service
    )
    meeting.raw_diarization = {"engine": DIARIZER_ENGINE, **diarization_data}
```

```python
# tasks/process_meeting.py:97-133 (the path rediarize must reuse)
if meeting.is_dual_track:
    meeting_dir = get_meeting_path(meeting.id)
    mic_path = str(meeting_dir / DUAL_MIC_OUTPUT)
    system_path = str(meeting_dir / DUAL_SYSTEM_OUTPUT)
    host_vad = vad_service.compute_vad_segments(mic_path)
    host_turns = host_turns_from_vad(host_vad)
    diar_result = diarizer.diarize(system_path, min_speakers=..., max_speakers=...)
    remote_turns = vad_service.mask_turns_to_vad(diar_result.turns, system_vad)
    diar_result = build_dual_diarization(host_turns, remote_turns)
```

Repo conventions: fake Engines in tests (see `tests/test_task_failure_lifecycle.py`
and `tests/test_pyannote_exclusive.py`). Do not load pyannote or GPU.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Dual-track unit tests | `.\venv\Scripts\python.exe -m pytest tests/test_dual_track.py -q` | all pass |
| New rediarize tests | `.\venv\Scripts\python.exe -m pytest tests/test_reprocess_dual_track.py -q` | all pass |
| Related task tests | `.\venv\Scripts\python.exe -m pytest tests/test_pyannote_exclusive.py tests/test_task_failure_lifecycle.py tests/test_dual_track.py -q` | all pass |
| Ordinary backend suite | `.\venv\Scripts\python.exe -m pytest -m "not model_load and not model_inference" -q` | exit 0 |
| Diff whitespace | `git diff --check` | exit 0 |

## Scope

**In scope**:

- `tasks/dual_track.py` (add the shared runner; keep existing helpers)
- `tasks/process_meeting.py` (call the shared runner for the dual-track
  diarization branch only)
- `tasks/reprocess_task.py` (use the shared runner when
  `rerun_diarization` and pass `host_label`)
- `tests/test_reprocess_dual_track.py` (create)
- `tests/test_dual_track.py` (only if you add a thin test for the new
  function's path-missing error; optional)

**Out of scope**:

- Native VibeVoice diarization (`has_native_diarization`). Re-diarize
  always uses the Diarizer port (pyannote), including for Meetings whose
  first run used native Turns. Do not change that product rule.
- Audio extraction / `extract_dual_audio`.
- Frontend reprocess dialogs.
- Plan 007 recovery behavior.
- `engines/`, `engine_runtimes/`, `install.ps1`.
- Splitting `tasks/shared.py`.

## Git workflow

- Branch: `advisor/008-rediarize-dual-track`
- Commits: `test: cover dual-track rediarize` then
  `fix(tasks): rediarize dual-track via host/remote path`
- Do NOT push unless instructed.

## Steps

### Step 1: Extract `run_dual_track_diarization` with a failing task test

Add to `tasks/dual_track.py`:

```python
def run_dual_track_diarization(
    meeting_id: str,
    diarizer,
    vad_service,
    min_speakers: int | None,
    max_speakers: int | None,
) -> DiarizationResult:
    """Host Turns from mic VAD; remote Turns from Diarizer on the system track."""
```

Implementation must match `process_meeting.py:97-119`:

1. `meeting_dir = get_meeting_path(meeting_id)`
2. `mic_path = meeting_dir / DUAL_MIC_OUTPUT`, `system_path = meeting_dir / DUAL_SYSTEM_OUTPUT`
3. If either file is missing, raise `RuntimeError` naming the missing path
   and saying dual-track reprocessing needs the processed tracks from the
   first Job.
4. Host: `host_turns_from_vad(vad_service.compute_vad_segments(str(mic_path)))`
5. Remote: `diarizer.diarize(str(system_path), min_speakers=..., max_speakers=...)`
   then `mask_turns_to_vad` with system VAD.
6. Return `build_dual_diarization(host_turns, remote_turns)`.

Do **not** write `meeting.raw_diarization` inside this function. Persistence
stays in the task.

Create `tests/test_reprocess_dual_track.py`:

- Sqlite meeting with `is_dual_track=True`, `raw_transcription` containing
  one Word, `audio_filepath` pointing at a dummy mix path.
- Create empty `mic_processed.wav` and `system_processed.wav` under
  `get_meeting_path(meeting.id)` (monkeypatch `config.get_meeting_path` /
  `tasks.dual_track.get_meeting_path` to `tmp_path / meeting.id`).
- Fake diarizer whose `diarize(path, ...)` records `path` and returns a
  `DiarizationResult` with one remote Turn `SPEAKER_00`.
- Fake VAD: mic → `[(0.0, 1.0)]`, system → `[(0.5, 1.5)]`.
- Monkeypatch `make_diarizer`, `VadService.compute_vad_segments`,
  `VadService.mask_turns_to_vad` (identity), `tasks.shared.publish_event`.
- Call `rediarize_task(meeting_id, job_id)` **before** changing
  `reprocess_task.py` and assert today's bug: `diarize` was called with
  `audio_filepath` (the mix), not the system track. Then invert that
  assertion in step 2.

Also assert a missing-track `RuntimeError` when the wavs are absent, once
the helper exists (can wait for step 2).

Use the session/job setup from `tests/test_task_failure_lifecycle.py`.

**Verify**: `.\venv\Scripts\python.exe -m pytest tests/test_reprocess_dual_track.py -q`
→ the "diarize called with system track" assertion fails on current code.

### Step 2: Switch both tasks onto the helper

In `tasks/process_meeting.py` dual-track branch, replace the inlined block
with:

```python
diar_result = run_dual_track_diarization(
    meeting.id, diarizer, vad_service,
    meeting.min_speakers, meeting.max_speakers,
)
```

Keep the existing `raw_diarization` dict shape, including `"host_label": HOST_SPEAKER`
and `"engine": DIARIZER_ENGINE`. Keep native/single-track branches untouched.

In `tasks/reprocess_task.py` when `rerun_diarization`:

```python
if meeting.is_dual_track:
    diar_result = run_dual_track_diarization(...)
    meeting.raw_diarization = {
        "engine": DIARIZER_ENGINE,
        "turns": [t.to_dict() for t in diar_result.turns],
        "exclusive_turns": (
            [t.to_dict() for t in diar_result.exclusive_turns]
            if diar_result.exclusive_turns is not None else None
        ),
        "overlaps": diar_result.overlaps,
        "host_label": HOST_SPEAKER,
    }
    bounded_turns = diar_result.turns
    bounded_exclusive_turns = diar_result.exclusive_turns
else:
    # existing pyannote + prepare_diarization path
```

When calling `name_speakers`, pass
`host_label=HOST_SPEAKER if meeting.is_dual_track else None` (same as
process_meeting). Apply this on both `rerun_diarization=True` and `False`
so re-identify also keeps `"You"`.

Flip the test from step 1: `diarize` must be called with a path ending in
`system_processed.wav`, not the mix. After success, stored
`raw_diarization["host_label"] == "HOST"`, and some Speaker has
`display_name == "You"` (or `identified_by == "host_track"`).

**Verify**: `.\venv\Scripts\python.exe -m pytest tests/test_reprocess_dual_track.py tests/test_dual_track.py tests/test_pyannote_exclusive.py tests/test_task_failure_lifecycle.py -q`
→ all pass.

### Step 3: Confirm single-track rediarize is unchanged

`tests/test_pyannote_exclusive.py::test_process_meeting_and_rediarize_tasks_with_exclusive_turns`
must still pass without modification. If it fails, you changed the
single-track path — revert that part.

**Verify**: same command as step 2, plus
`.\venv\Scripts\python.exe -m pytest -m "not model_load and not model_inference" -q`.

## Test plan

- New `tests/test_reprocess_dual_track.py`:
  - rediarize calls Diarizer on system track
  - host Speaker named `"You"`
  - missing processed tracks raise `RuntimeError` and mark Job FAILED
    (via existing `meeting_job`)
  - single-track meeting still uses `audio_filepath` (one extra test)
- Pattern: `tests/test_task_failure_lifecycle.py` + fake diarizer from
  `tests/test_pyannote_exclusive.py`.
- Do not add GPU/model tests.

## Done criteria

- [ ] `.\venv\Scripts\python.exe -m pytest tests/test_reprocess_dual_track.py tests/test_dual_track.py tests/test_pyannote_exclusive.py tests/test_task_failure_lifecycle.py -q` exits 0
- [ ] `.\venv\Scripts\python.exe -m pytest -m "not model_load and not model_inference" -q` exits 0
- [ ] `rg "run_dual_track_diarization" tasks/process_meeting.py tasks/reprocess_task.py` matches both
- [ ] `rediarize_task` path for `is_dual_track` does not call `diarizer.diarize(audio_path)`
- [ ] `name_speakers` in `tasks/reprocess_task.py` passes `host_label`
- [ ] No files outside the in-scope list are modified
- [ ] `plans/README.md` status row for 008 updated

## STOP conditions

- Current-state excerpts no longer match.
- Dual-track processed files are not named `mic_processed.wav` /
  `system_processed.wav` in live `audio_service.py`.
- You think rediarize should call VibeVoice native diarization. It must not;
  report instead.
- `build_dual_diarization` return shape changed (no `.turns` /
  `.exclusive_turns` / `.overlaps`).
- Need to touch `engines/` or rewrite `prepare_diarization`.

## Maintenance notes

- First-run native diarization (VibeVoice) still only lives in
  `process_meeting_task`. Re-diarize is always the Diarizer port. That is
  deliberate: Reprocessing means "run the Diarizer again".
- Reviewer should check `raw_diarization` JSON keys stay compatible with
  `turns_from_stored` / `exclusive_turns_from_stored` /
  `overlaps_from_stored` in `tasks/shared.py`.
- Plan 010 may extract an API enqueue helper; it must not fold this
  diarization dispatch back into `api/meetings.py`.
