# Plan 037: Nemotron reads its settings from Preferences, not from code

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report; do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**: run
> `git diff --stat c88c4cd..HEAD -- preferences.py engines/__init__.py engines/isolated_python.py engines/pyannote.py engines/health.py engine_runners/nemotron_diarization.py config.py frontend/src/components/settings/ frontend/src/api.ts tests/test_engines.py tests/test_preferences_api.py tests/engine_smoke/`.
> Any output is a STOP condition until compared with the excerpts below.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: 022, 023 (Nemotron Diarizer, merged)
- **Category**: bug + tech debt
- **Planned at**: commit `c88c4cd`, 2026-10-10
- **Source**: the user, 2026-10-10: "vamos resolver o bug do threshold antes
  então, e tirar esses valores fixos do código".

## Why this matters

The user's saved Preferences pick Nemotron 3 Diarization with
`clustering_threshold: 0.55`. That number never reaches Nemotron:

- `make_diarizer` builds Nemotron with a literal `threshold=0.5`.
- `clustering_threshold` is a pyannote clustering knob. Nemotron's `threshold`
  is something else: the speaker probability that counts as speech.

The user is about to calibrate the Diarizer on their Meetings (issue
`.scratch/agent-operation/issues/02-split-segment.md`, shape 2). A
calibration needs every Nemotron knob to be a Preference. The value must also
be recorded in each Job's RunConfig, so the bench can see what a Meeting ran
with. Three values are fixed in code today:

| Value | Where | Meaning |
|---|---|---|
| `threshold=0.5` | `engines/__init__.py:make_diarizer`, `engines/isolated_python.py` default, `engine_runners/nemotron_diarization.py` fallback | speaker probability that counts as speech |
| `MIN_SPEAKER_SECONDS = 5.0` | `engines/isolated_python.py` | a Speaker with less total speech is dropped |
| `device="cuda"` | `engines/__init__.py:make_diarizer`, `engines/health.py:diarizer_status` | where Nemotron runs |

## Decisions

- Two new fields in `DiarizationPrefs`, both used only by Nemotron, with
  explicit defaults equal to today's literals so nothing changes for anyone:
  - `speech_threshold: float = Field(default=0.5, gt=0.0, lt=1.0)`;
  - `min_speaker_seconds: float = Field(default=5.0, ge=0.0, le=60.0)`.
- They are Preferences, not `config.py` settings, because they affect the
  result. `RunConfig` already copies `prefs.diarization`, so every Job records
  them with no change to `run_config.py`.
- The device is an install fact, not a result choice: it becomes
  `settings.nemotron_diarization_device: str = "cuda"` in `config.py`, next to
  `nemotron_diarization_model_path`, and both callers read it.
- pyannote receives only its own knobs. Today `make_diarizer` hands pyannote
  `model_dump(exclude_none=True, exclude={"engine"})`; with the new fields that
  would send `speech_threshold` to pyannote. Pass only the keys of pyannote's
  mapping instead (rename `_CLUSTERING_PREF_TO_PARAM` to
  `CLUSTERING_PREF_TO_PARAM`, since `engines/__init__.py` now reads it).
- No silent fallbacks remain: `IsolatedPythonDiarizer` takes `threshold` and
  `min_speaker_seconds` as required keyword arguments, and the runner reads
  `options["threshold"]` without a default.
- The stored `clustering_threshold` stays as it is. It is a pyannote value and
  the Settings page already hides it while Nemotron is selected.
- Out of scope: `bench/run_nemotron_diarization.py` keeps its own `--threshold`
  default (a standalone bench script that runs in the Nemotron venv).

## Current state

`preferences.py`:

```python
class DiarizationPrefs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    engine: Literal["pyannote", "nemotron-3-diarization"] = "pyannote"
    clustering_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    Fa: float | None = Field(default=None, ge=0.0, le=5.0)
    Fb: float | None = Field(default=None, ge=0.0, le=5.0)
```

The PUT handler (`preferences.py`, around line 262) builds the diarization
patch from `DiarizationPrefs.model_fields` through `_accepted_number`, so new
numeric fields are accepted and range-checked with no handler change. The
patch replaces the whole block, which is why the frontend must always send
every field (step 5).

`engines/__init__.py`:

```python
def make_diarizer(run_config: "RunConfig", *, hf_token: str = "") -> Diarizer:
    """Build the Diarizer selected in the Job's RunConfig."""
    if run_config.diarization.engine == "nemotron-3-diarization":
        from config import settings
        from .isolated_python import IsolatedPythonDiarizer
        return IsolatedPythonDiarizer(model_path=settings.nemotron_diarization_model_path,
            device="cuda", threshold=0.5)
    from .pyannote import PyannoteDiarizer
    return PyannoteDiarizer(
        clustering=run_config.diarization.model_dump(exclude_none=True, exclude={"engine"}),
        auth_token=hf_token,
    )
```

`engines/isolated_python.py`:

```python
# A Speaker with less total speech than this across the whole Meeting is dropped.
# Nemotron can open a speaker channel for a few seconds of echo or crosstalk (the
# 2026-09-25 bench found 3.6 s on a dual-track system track); that Speaker would get
# no Words and surface as an empty "Participant N".
MIN_SPEAKER_SECONDS = 5.0
...
class IsolatedPythonDiarizer:
    def __init__(self, *, model_path: str, device: str, threshold: float = 0.5):
        self.model_path, self.device = model_path, device
        self.options = {"threshold": threshold}
    ...
    def diarize(self, audio_path: str, min_speakers=None, max_speakers=None) -> DiarizationResult:
        ...
        dropped = {speaker for speaker, seconds in speech.items() if seconds < MIN_SPEAKER_SECONDS}
        if dropped:
            log.info("[nemotron] dropped %s: under %.0f s of speech", sorted(dropped), MIN_SPEAKER_SECONDS)
```

`engine_runners/nemotron_diarization.py`:

```python
        segments = self.processor.extract_speaker_dict(
            logits, inputs.attention_mask, threshold=float(self.request.options.get("threshold", 0.5))
        )[0]
```

`engines/health.py:diarizer_status`:

```python
        preset = {"engine": engine, "model_path": settings.nemotron_diarization_model_path, "device": "cuda"}
```

`engines/pyannote.py`: `_CLUSTERING_PREF_TO_PARAM = {"clustering_threshold":
"threshold", "Fa": "Fa", "Fb": "Fb"}`, used at lines ~108 and ~117.

Frontend:
- `frontend/src/api.ts`, `interface DiarizationPrefs { engine?; clustering_threshold?; Fa?; Fb? }`;
- `frontend/src/components/settings/preferencesPayload.ts`,
  `buildDiarizationPayload(engine, clusteringThreshold)`, tested in
  `preferencesPayload.test.ts`;
- `usePreferencesForm.ts` holds the form state (`clusterThreshold`,
  `switchPenalty`, ...) and `save()` calls `buildDiarizationPayload`;
- `DiarizationTab.tsx` shows the pyannote token and "Speaker separation"
  slider only when `usesPyannote`, and the "Speaker attribution smoothing"
  slider always. Copy its slider markup for the new controls.

Tests that construct the adapter directly:
`tests/engine_smoke/test_load.py:16` and `tests/engine_smoke/test_inference.py:18`
(`IsolatedPythonDiarizer(model_path=..., device="cuda")`). They are opt-in
`model_*` tests; they must still construct after the change.

## Steps

Call the `tdd` skill first. The seams for this plan are agreed:
`make_diarizer` + `IsolatedPythonDiarizer.diarize` (with `launch_engine`
monkeypatched, as `test_nemotron_factory_and_adapter_filter_short_speakers`
does), the preferences PUT route, and `buildDiarizationPayload`. Each step
below writes its test red first.

1. **Preferences.** In `tests/test_preferences_api.py`, add a test that a
   PUT of `{"diarization": {"engine": "nemotron-3-diarization",
   "speech_threshold": "0.4", "min_speaker_seconds": 2, ...}}` stores both
   numbers, and that out-of-range values (`speech_threshold: 1.5`,
   `min_speaker_seconds: -1`) are dropped. Then add the two fields to
   `DiarizationPrefs` with a comment saying they are Nemotron's. Move the
   reason in the `MIN_SPEAKER_SECONDS` comment (the 3.6 s echo channel) onto
   `min_speaker_seconds`.
   Verify: `uv run --extra dev pytest -q tests/test_preferences_api.py tests/test_preferences.py`.
   If an existing assertion compares the whole `diarization` dict of a PUT
   response, it now also contains the two defaults. Update that expected
   literal, and only that.
2. **Factory and adapter.** In `tests/test_engines.py`:
   - extend `test_default_diarizer_factory_stays_pyannote` so its
     `DiarizationPrefs` also sets `speech_threshold=0.3`, and keep the
     assertion `diarizer.clustering == {"clustering_threshold": 0.6}`;
   - add a test where the RunConfig carries `speech_threshold=0.35,
     min_speaker_seconds=3.0`: the built diarizer's `options` are
     `{"threshold": 0.35}`, and a 3.5 s Speaker (`Turn(1, 4.5, "SPEAKER_02")`)
     is kept, whereas the existing test (defaults) still drops it;
   - assert the diarizer's `device` equals `settings.nemotron_diarization_device`.
   Then:
   - add `nemotron_diarization_device: str = "cuda"` to `config.py` after
     `nemotron_diarization_model_path`;
   - `IsolatedPythonDiarizer.__init__(self, *, model_path, device, threshold,
     min_speaker_seconds)` with no defaults; `diarize` uses
     `self.min_speaker_seconds`; delete `MIN_SPEAKER_SECONDS`;
   - `make_diarizer` passes `device=settings.nemotron_diarization_device`,
     `threshold=run_config.diarization.speech_threshold`,
     `min_speaker_seconds=run_config.diarization.min_speaker_seconds`;
   - rename `_CLUSTERING_PREF_TO_PARAM` to `CLUSTERING_PREF_TO_PARAM` in
     `engines/pyannote.py` (all three uses), and in `make_diarizer` pass
     `clustering=run_config.diarization.model_dump(include=set(CLUSTERING_PREF_TO_PARAM), exclude_none=True)`;
   - `engines/health.py:diarizer_status` uses
     `settings.nemotron_diarization_device`;
   - the two `tests/engine_smoke` constructors pass
     `threshold=DiarizationPrefs().speech_threshold,
     min_speaker_seconds=DiarizationPrefs().min_speaker_seconds` and
     `device=settings.nemotron_diarization_device`.
   Verify: `uv run --extra dev pytest -q tests/test_engines.py` passes, and
   `rg -n "MIN_SPEAKER_SECONDS|threshold=0.5|\"device\": \"cuda\"|device=\"cuda\"" engines tests`
   prints nothing.
3. **Runner.** In `engine_runners/nemotron_diarization.py`, read
   `float(self.request.options["threshold"])` with no fallback. No test runs
   this file without the model; verify with
   `rg -n "get\(\"threshold\"" engine_runners` printing nothing.
4. **RunConfig record.** Add one assertion where `resolve_run_config` is
   already tested (`rg -n "resolve_run_config" tests`): a Preferences with
   `speech_threshold=0.4` yields `run_config.diarization.speech_threshold == 0.4`,
   and `run_config.model_dump()` contains it (that dump is what a Job stores).
   It probably passes at once, since `RunConfig` copies `prefs.diarization`;
   that is fine, because it locks the record the calibration depends on.
5. **Frontend.**
   - `api.ts`: add `speech_threshold?: number` and
     `min_speaker_seconds?: number` to `DiarizationPrefs`.
   - `preferencesPayload.ts`: change the signature to one object,
     `buildDiarizationPayload({ engine, clusteringThreshold, speechThreshold, minSpeakerSeconds })`.
     It always includes `speech_threshold` and `min_speaker_seconds`, because
     the PUT replaces the whole block. Update the three existing tests to the
     new signature, then add one test that switching to pyannote still sends
     the Nemotron values. Write the tests first.
   - `usePreferencesForm.ts`: state `speechThreshold` (default 0.5) and
     `minSpeakerSeconds` (default 5), loaded from
     `p.diarization?.speech_threshold ?? 0.5` and
     `p.diarization?.min_speaker_seconds ?? 5`, returned from the hook and
     passed to the payload.
   - `DiarizationTab.tsx`: when `diarizerEngine === "nemotron-3-diarization"`,
     show two controls in the same style as "Speaker attribution smoothing":
     - "Speech threshold": a range from 0.30 to 0.80, step 0.05, labelled
       `toFixed(2)`. Help text: "Speaker probability Nemotron counts as
       speech. Lower keeps quieter and shorter speech, and opens more turns;
       higher keeps only confident speech." End labels "more speech" and
       "less speech".
     - "Minimum speech per Speaker": a number input, 0–60, step 1, suffix
       "s". Help text: "A Speaker with less speech than this in the whole
       Meeting is dropped; its words go to the nearest Speaker. Catches echo
       and crosstalk channels."
   Verify: `cd frontend && npm test` and `npx tsc --noEmit` pass.
6. **Docs.** Run
   `rg -n -i "clustering threshold|speech threshold|min.?speaker|nemotron" README.md GLOSSARY.md docs/`.
   Where a doc describes Diarization settings, say that Nemotron takes a
   speech threshold and a minimum speech per Speaker. Do not edit ADRs; they
   are records. If no doc describes the settings, change nothing and say so
   in the report.
7. **Gates.** `uv run --extra dev pytest -q` from the repo root, and
   `npm test` in `frontend/`. Both pass. Update the row in
   `plans/README.md` to DONE.

## Hard boundaries

- In scope: `preferences.py`, `config.py`, `engines/__init__.py`,
  `engines/isolated_python.py`, `engines/pyannote.py` (rename only),
  `engines/health.py`, `engine_runners/nemotron_diarization.py`, the tests
  named above, the four frontend files above plus `preferencesPayload.test.ts`,
  docs from step 6, and `plans/README.md`.
- Out of scope: `bench/`, `run_config.py`, `tasks/`, the stored
  `storage/preferences.json`, any migration.
- Never touch the real database, `storage/`, `models/`, `.env`, and never run
  the CLI or the app against the live instance. Do not run the `model_*`
  tests (they need the GPU and weights).
- Every file change goes through the Edit and Write tools. No `sed -i`,
  no scripted rewrites.

## STOP conditions

- The drift check prints changes to an in-scope file.
- Something other than `make_diarizer`, the two smoke tests and
  `engines/health.py` constructs `IsolatedPythonDiarizer` or reads
  `MIN_SPEAKER_SECONDS` (`rg -n "IsolatedPythonDiarizer\(|MIN_SPEAKER_SECONDS"`).
- `RunConfig` is validated somewhere against stored Job JSON in a way that
  rejects the new fields. They have defaults, so old Jobs should load; if a
  test shows otherwise, stop.
- The preferences PUT handler needs more than the new fields to accept them.

## Done criteria

- `uv run --extra dev pytest -q`: all pass.
- `cd frontend && npm test`: all pass.
- `rg -n "MIN_SPEAKER_SECONDS|threshold=0.5|options.get\(\"threshold\"" engines engine_runners tests`:
  no output.
- `rg -n "\"cuda\"" engines/__init__.py engines/health.py`: no output.

## Maintenance note

The calibration bench (issue 02, shape 2) varies `speech_threshold`,
`min_speaker_seconds` and `speaker_switch_penalty`. It reads what a Meeting
ran with from its Job's `run_config.diarization`. A new Nemotron knob belongs
in `DiarizationPrefs` too, and must not be passed to pyannote (keep the
`include=` in `make_diarizer`).
