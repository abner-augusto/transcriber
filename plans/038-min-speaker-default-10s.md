# Plan 038: The default minimum speech per Speaker becomes 10 s

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report; do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**: confirm plan 037 is DONE in `plans/README.md`,
> then run
> `git diff --stat ceb9945..HEAD -- preferences.py frontend/src/components/settings/ tests/test_preferences_api.py`.
> Any output is a STOP condition until compared with the excerpts below.

## Status

- **Priority**: P2
- **Effort**: XS
- **Risk**: LOW
- **Depends on**: 037
- **Category**: tuning
- **Planned at**: commit `ceb9945`, 2026-10-10
- **Source**:
  - the user, 2026-10-10 ("2. sim"), approving a code default of 10 s;
  - the bench recorded in `.scratch/agent-operation/issues/02-split-segment.md`,
    section "Bench, 2026-10-10".

## Why this matters

Nemotron opens short speaker channels for echo or for a few words of a real
participant. A Speaker under `min_speaker_seconds` of total speech is dropped,
and its Words go to the nearest Speaker.

The bench across every Meeting diarized by Nemotron:
- in Sinop, raising the minimum from 5 s to 10 s drops a 7.1 s channel and
  gives 15 hand-corrected Words back to the right person, with no new
  disagreement;
- in another Meeting it drops a 9.0 s channel whose Words the user had
  already merged into the same Speaker the drop picks;
- in the single-track control, the smallest real Speaker has 37 s, so
  nothing changes there.

The user's saved Preference is already 10 s. This plan changes only the
default that a fresh install, or a Preferences file without the field, gets.

## Current state

`preferences.py`, in `DiarizationPrefs`:

```python
    # A Speaker with less total speech than this across the whole Meeting is dropped.
    # Nemotron can open a speaker channel for a few seconds of echo or crosstalk (the
    # 2026-09-25 bench found 3.6 s on a dual-track system track); that Speaker would get
    # no Words and surface as an empty "Participant N".
    min_speaker_seconds: float = Field(default=5.0, ge=0.0, le=60.0)
```

`frontend/src/components/settings/usePreferencesForm.ts`:

```ts
  const [minSpeakerSeconds, setMinSpeakerSeconds] = useState(5);
  ...
    setMinSpeakerSeconds(p.diarization?.min_speaker_seconds ?? 5);
```

Tests that pin the default value:
- `tests/test_preferences_api.py:37` expects `"min_speaker_seconds": 5.0` in a
  whole-dict assertion;
- `frontend/src/components/settings/preferencesPayload.test.ts` lines 11, 20
  and 31 pass `5` as an input. Those are inputs, not the default, so they stay.

## Steps

1. Add a test in `tests/test_preferences.py` that `DiarizationPrefs()` has
   `min_speaker_seconds == 10.0`. Run
   `uv run --extra dev pytest -q tests/test_preferences.py` and see it fail.
2. In `preferences.py`, change the default to `10.0`. Add one line to the
   comment above the field: "10 s since the 2026-10-10 bench: a 7.1 s and a
   9.0 s channel were each a real participant's stray Words."
3. Update `tests/test_preferences_api.py:37` from `5.0` to `10.0`. That is the
   only change in that file.
4. In `usePreferencesForm.ts`, change both `5`s above to `10`.
5. Gates: `uv run --extra dev pytest -q` from the root, and `npm test` in
   `frontend/`. Both pass. Mark 038 DONE in `plans/README.md`.

## Hard boundaries

- In scope: `preferences.py`, `tests/test_preferences.py`,
  `tests/test_preferences_api.py`, `usePreferencesForm.ts`, `plans/README.md`.
- Never touch `storage/`, the real database, `models/` or `.env`, and never
  run the app or the CLI against the live instance.
- Every file change goes through the Edit and Write tools.

## STOP conditions

- The drift check prints changes.
- A test other than `tests/test_preferences_api.py:37` fails because of the
  new default.

## Done criteria

- `uv run --extra dev pytest -q`: all pass.
- `cd frontend && npm test`: all pass.
- `rg -n "default=5\.0" preferences.py`: no output.

## Maintenance note

A future bench that finds a real participant with less than 10 s of speech
is the signal to lower this again. The value is a Preference, so the user can
override it per install without a code change.
