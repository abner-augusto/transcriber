# Plan 016: One place for Preferences, and a RunConfig recorded per Job

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` and the status of
> `.scratch/architecture-review/issues/03-run-config.md`.
>
> **Drift check (run first)**: `git diff --stat ce66ade..HEAD -- preferences.py presets.py config.py main.py api/preferences.py api/model_settings.py api/meetings.py engines/__init__.py engines/pyannote.py engines/alignment.py services/speaker_id_service.py tasks/ models/job.py database.py frontend/src/api.ts`

## Status

- **Priority**: P2
- **Effort**: L
- **Risk**: MED (user settings on disk move)
- **Depends on**: none. Coordinate with plans 014 and 015 (both touch
  `tasks/process_meeting.py`; 014 adds the `vocabulary_correction` preference).
  Land 015 first if both are pending: RunConfig is handed to adapters it
  reshapes.
- **Category**: architecture (deepening) + bug (CWD-relative settings file)
- **Planned at**: commit `ce66ade`, 2026-09-24
- **Source**: design session 2026-09-24 on ticket 03. The user asked to
  centralize preferences in one place as far as possible.

## Why this matters

User-tunable configuration lives in three files and is merged in five places:

| Where | What |
|-------|------|
| `preferences.json` (CWD-relative, `preferences.py:6`) | vocabulary, profiles toggle, HF token, switch penalty, forced alignment, whisper DTW, clustering, vocabulary profiles |
| `storage/settings.json` (`presets.py:123`) | default Preset |
| `.env` / `config.py` | machine paths **and** duplicated defaults (`whisper_dtw_enabled`, `whisper_dtw_preset`, `forced_alignment_enabled`, `forced_alignment_model`) |

Readers: `engines/__init__.py` (DTW merge), `tasks/process_meeting.py`
(forced alignment, bool-or-dict), `engines/pyannote.py` (re-reads clustering
on every call), `services/speaker_id_service.py`, `api/meetings.py` (default
vocabulary), `engines/alignment.py`. Writers: `main.py::update_preferences`
(field-by-field dict validation), `api/preferences.py` (vocabulary profiles),
`api/model_settings.py` (default Preset). Because `preferences.json` is
CWD-relative, the API and the worker can silently read different files.
No Job records the configuration it ran with.

## Decisions (from the design session — do not re-litigate)

1. **One model, one file.** A pydantic `Preferences` model defines every
   user-tunable field, its default, and its bounds. It is stored in one file,
   `storage/preferences.json` (absolute, via `config.get_storage_path()`).
   The default Preset moves into it (`default_preset`), and
   `storage/settings.json` goes away.
2. **`.env` keeps only machine facts**: binary and interpreter paths,
   storage/database/redis URLs, timeouts, and the HF token as a fallback.
   The duplicated user defaults leave `config.py`.
3. **One-time migration** on first load: if `storage/preferences.json` does
   not exist, merge the legacy `./preferences.json` (repo root) and
   `storage/settings.json` into it, validate, write it, and rename the legacy
   files to `*.migrated`. Log what moved. Never lose a user value that
   validates; log and drop one that does not.
4. **All reads and writes go through one module** (`preferences.py`):
   `load() -> Preferences`, `update(patch) -> Preferences`, `public()` (secret
   masked). Every API route that touches preferences uses it; unknown fields
   are rejected by the model, not ignored by hand.
5. **RunConfig**: resolved when the Job **starts running** (same rule as
   today's "default Preset at the time the Job runs"), from `Preferences` +
   the resolved Preset. Stored as `jobs.run_config` (JSON).
6. **RunConfig contents**: everything that changes the result — resolved
   Preset (id, engine, model and options), forced alignment, whisper DTW,
   diarization clustering overrides, speaker switch penalty, Voice Profiles
   on/off, Vocabulary Correction on/off (plan 014). Never secrets, never
   machine paths beyond what the Preset itself names.
7. **Engines get configuration through their factories**
   (`make_transcriber(run_config)`, `make_diarizer(run_config)`,
   `make_aligner(run_config)`), never by reading preferences. pyannote stops
   re-reading the file on every call; it applies the overrides it was given.
8. Moving preferences into the database is ticket 05 (SQLite), not this plan.

## Target interface

```python
# preferences.py
class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    default_preset: str | None = None
    default_vocabulary: str = Field("", max_length=2000)
    speaker_profiles_enabled: bool = False
    hf_auth_token: str = ""
    speaker_switch_penalty: float = Field(SPEAKER_SWITCH_PENALTY, ge=0.0, le=2.0)
    forced_alignment: ForcedAlignmentPrefs = ForcedAlignmentPrefs()   # enabled, model, device
    whisper_dtw: WhisperDtwPrefs = WhisperDtwPrefs()                  # enabled, preset
    diarization: DiarizationPrefs = DiarizationPrefs()                # clustering_threshold, Fa, Fb (optional, bounded)
    vocabulary_profiles: list[VocabularyProfile] = []
    # plan 014 adds: vocabulary_correction: VocabularyCorrectionPrefs

def load() -> Preferences
def update(patch: dict) -> Preferences      # validates the merged result; raises ValidationError
def public() -> dict                        # hf_auth_token masked
def hf_token() -> str                       # preference, else env fallback

# run_config.py
class RunConfig(BaseModel):
    preset: dict
    forced_alignment: ForcedAlignmentPrefs | None     # None = off
    whisper_dtw: WhisperDtwPrefs
    diarization: DiarizationPrefs
    speaker_switch_penalty: float
    speaker_profiles_enabled: bool

def resolve_run_config(meeting) -> RunConfig          # Preferences + resolve_preset(meeting.preset_id)
```

Keep the current wire format of `GET /api/settings` and
`PUT /api/settings/preferences` so the frontend keeps working; the handlers
become thin calls into `preferences.py`.

## Steps

1. **Characterize today**: tests for `load_preferences` defaults,
   `update_preferences` clamping/ignoring behavior in `main.py`, the
   bool-or-dict forced-alignment merge, the DTW merge in `make_transcriber`,
   and default-Preset storage. Record which invalid inputs are silently
   dropped today; keep dropping them (the API returns the current values) —
   do not start returning 422 for inputs the UI sends.
2. **`Preferences` model + storage + migration** (decisions 1–3), with tests
   for: fresh install, legacy root file only, legacy `settings.json` only,
   both, invalid legacy values, and that a second load does not migrate
   again. `presets.default_preset_id` / `set_default_preset` read and write
   `Preferences.default_preset`.
3. **Route everything through `preferences.py`** (decision 4): `main.py`,
   `api/preferences.py`, `api/model_settings.py`, `api/meetings.py`,
   `services/speaker_id_service.py`. `rg "load_preferences|save_preferences|_settings_path" --type py`
   returns only `preferences.py` and its tests.
4. **Trim `config.py`** (decision 2): remove the user defaults; anything that
   read them reads `Preferences` or `RunConfig`.
5. **`RunConfig` and factories** (decisions 5–7): `resolve_run_config` in the
   task when the Job starts; factories take it; pyannote applies overrides
   from its constructor; `jobs.run_config` column (migration line in
   `init_db`) written at Job start for every JobType. Reprocessing Jobs record
   their own RunConfig.
6. **Expose it**: `Job.to_dict()` includes `run_config`; no UI in this plan.

## Done criteria

- [ ] One settings file: `storage/preferences.json`; legacy files migrated and renamed
- [ ] `rg "load_preferences\(|preferences.json|settings.json" --type py` matches only `preferences.py`, its tests, and the migration
- [ ] No Engine or service reads preferences directly
- [ ] Every Job row has `run_config` after it starts; no secret in it
- [ ] Existing preferences API tests and frontend unchanged and passing
- [ ] `plans/README.md` row and ticket 03 status updated

## Carried over from the PR #1 review

- Add **Preferences** and **RunConfig** to `CONTEXT.md` when this plan lands.

## STOP conditions

- The migration would drop a value the user set that the new model rejects
  for a reason other than being out of bounds. Report it.
- Keeping the current wire format of the settings routes is impossible
  without a frontend change.
- pyannote cannot apply clustering overrides without re-instantiating per
  Job in a way that reloads weights.
