# Plan 023: A Diarization tab in Settings

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report; do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 748cf57..HEAD -- frontend/src/components/SettingsDialog.tsx frontend/src/components/settings/ frontend/src/api.ts`
> Plan 022 is expected to have changed `main.py`, `preferences.py` and
> `api/`. Any other drift in the listed frontend files is a STOP condition.

## Status

- **Execution status**: TODO
- **Priority**: P2
- **Effort**: S
- **Risk**: LOW (frontend only, no stored-shape change beyond plan 022)
- **Depends on**: plan 022 (the `diarization.engine` Preference and the
  `diarizers` list in `GET /api/settings`)
- **Category**: UI
- **Planned at**: commit `748cf57`, 2026-09-25
- **Source**: user request 2026-09-25: "uma categoria nova de diarizador" in
  the settings

## Why this matters

Plan 022 makes the Diarizer selectable, but Settings has only two tabs,
Presets (Transcribers) and Preferences. The diarization controls sit in
Preferences, mixed with Vocabulary and Voice Profiles: the Hugging Face token,
"Speaker attribution smoothing" and "Speaker separation". Some of them apply
only to pyannote. A Diarization tab gives the Diarizer the same standing as
the Transcriber. It is the only place to choose the Engine, and it shows only
the controls that apply to the chosen one.

## Decisions (do not re-litigate)

1. **A third tab, "Diarization"**, between Presets and Preferences. The tab
   type becomes `"presets" | "diarization" | "preferences"`.
2. **The tab reuses `usePreferencesForm`.** The Diarizer choice is a
   Preference (plan 022), so it saves through the same
   `PUT /api/settings/preferences`. `SettingsDialog.handleSave` saves when
   the tab is `preferences` **or** `diarization`.
3. **These controls move out of PreferencesTab**, unchanged in behavior:
   - "Hugging Face token": shown only when pyannote is selected (Nemotron
     needs none);
   - "Speaker separation" (clustering threshold): only when pyannote is
     selected, because Nemotron ignores it;
   - "Speaker attribution smoothing": always shown, because it applies to
     Segment derivation for every Diarizer.
4. **Engine choice as selectable cards**, one per entry of
   `settings.diarizers`. Each card has the name, a one-line description, and
   a health badge built from the `state`/`summary` that plan 022 returns,
   with the same wording and colors `PresetTab` uses for Preset health. A
   `blocked` Diarizer cannot be selected; the badge carries its `summary`.
5. **Two fixed notes** under the cards. They are copy, not logic:
   - Presets with native diarization (VibeVoice) do not use this choice.
   - On dual-track Meetings, the Diarizer only separates the remote speakers;
     the host comes from the mic track.
6. **No new endpoint.** The cards read `diarizers` from the same
   `GET /api/settings` response that `getPreferences` already calls.

## Current state

- `frontend/src/components/SettingsDialog.tsx` — two tabs; `handleSave`
  saves only when `tab === "preferences"`.
- `frontend/src/components/settings/PreferencesTab.tsx:21-85` — HF token,
  smoothing and separation controls.
- `frontend/src/components/settings/usePreferencesForm.ts` — loads with
  `getPreferences()`, saves with `updatePreferences({... diarization:
  clusterThreshold == null ? {} : { clustering_threshold } })`.
- `frontend/src/api.ts:207-230` — `DiarizationPrefs` (numbers only),
  `getPreferences()` returns only `data.preferences` from `GET /settings`.

## Steps

### Step 1: Types and API

- `DiarizationPrefs.engine?: "pyannote" | "nemotron-3-diarization"`.
- A `DiarizerOption` type matching plan 022's payload (`id`, `name`,
  `description`, `state`, `summary`).
- A `getSettings()` that returns `{ preferences, diarizers }`, with
  `getPreferences()` kept as a thin wrapper for existing callers.

**Verify**: `npm run build` (in `frontend/`) passes.

### Step 2: Form state

In `usePreferencesForm`, load `diarizerEngine` (default `"pyannote"`) and
`diarizers`. Save `diarization: { engine: diarizerEngine, ...threshold }`,
where the threshold is included only when it is set, as today.

**Verify**: a vitest unit test for the payload built by `save()`, if the
function is extracted pure (`buildPreferencesPayload`). It must cover:
pyannote + default threshold, pyannote + threshold, and Nemotron (whose
payload still keeps the stored threshold, so switching back restores it).
`npm test` passes.

### Step 3: DiarizationTab

Create `frontend/src/components/settings/DiarizationTab.tsx`. It holds the
engine cards and notes (decisions 4 and 5), then the moved controls (decision
3), and uses the same Tailwind classes as the current PreferencesTab
controls. Remove those controls from `PreferencesTab`.

### Step 4: Dialog

Add the tab to `SettingsDialog` (decision 1) and make `handleSave` cover it
(decision 2). Unsaved edits must survive switching between Diarization and
Preferences, which they will, because the form is owned by the dialog.

**Verify**: `npm run build` and `npm test` pass.

### Step 5: Manual check (user's machine)

`start.ps1`, then open Settings:

- Diarization shows both Engines with health. pyannote is selected on a
  fresh `preferences.json`.
- Selecting Nemotron hides the token and separation controls; Save, reopen,
  and the choice persists.
- A Meeting queued afterwards stores `engine == "nemotron-3-diarization"` in
  its diarization (plan 022's Step 8 covers the Job side).
- The Preferences tab no longer shows the moved controls.

## Done criteria

- [ ] Settings has a Diarization tab that selects the Diarizer through Preferences.
- [ ] pyannote-only controls appear only for pyannote; smoothing is always shown.
- [ ] Blocked Diarizers are visible but not selectable, with their reason.
- [ ] `npm run build` and `npm test` pass.
- [ ] Manual check on the user's machine.

## STOP conditions

- Plan 022 is not DONE, or `GET /api/settings` lacks `diarizers`.
- Drift in the frontend files listed in "Current state".
- The design needs a new endpoint or a backend change (that belongs to plan 022).

## Outcome

_To be filled in by the executor._
