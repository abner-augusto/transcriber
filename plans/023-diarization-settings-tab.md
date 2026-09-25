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

- **Execution status**: DONE
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

- [x] Settings has a Diarization tab that selects the Diarizer through Preferences.
- [x] pyannote-only controls appear only for pyannote; smoothing is always shown.
- [x] Blocked Diarizers are visible but not selectable, with their reason.
- [x] `npm run build` and `npm test` pass.
- [x] Manual check on the user's machine.

## STOP conditions

- Plan 022's backend is not on this branch: `GET /api/settings` lacks
  `diarizers`, or `DiarizationPrefs` lacks `engine`. Plan 022 may still be
  IN PROGRESS for its Step 8, a manual check in the app that needs this tab;
  that is not a STOP.
- Drift in the frontend files listed in "Current state".
- The design needs a new endpoint or a backend change (that belongs to plan 022).

## Outcome

Implemented the Diarization tab with selectable engine cards, state-based health badges, blocked-engine reasons, and the two explanatory notes. Moved the Hugging Face token and Speaker separation controls out of Preferences; they appear only for pyannote. Speaker attribution smoothing appears for both engines. The dialog-owned form loads `diarization.engine` and the `diarizers` list from `GET /api/settings`, saves through the existing Preferences endpoint from either Preferences-related tab, and retains a stored clustering threshold while Nemotron is selected.

Verification results:

- Drift check: `git diff --stat 748cf57..HEAD -- frontend/src/components/SettingsDialog.tsx frontend/src/components/settings/ frontend/src/api.ts` returned no output. Plan 022's backend contract is present: `main.py` returns `diarizers` and `preferences.py` defines `DiarizationPrefs.engine`.
- Step 1: `npm run build` passed; Vite transformed 120 modules and built successfully.
- Step 2: `npm test` passed with 39 tests across 6 files, including the three payload cases (pyannote default threshold, pyannote override, and Nemotron retaining a stored threshold).
- Step 4/final frontend verification: `npm run build` passed; Vite transformed 122 modules and built successfully. `npm test` passed with 40 tests across 6 files.
- Backend regression suite: `.\.venv\Scripts\python.exe -m pytest -q tests` passed with 370 passed and 20 skipped in 35.42s.

The only unchecked Done criterion is the manual check on the user's machine. It remains for the reviewer and user: open Settings, check engine health and persistence, verify the pyannote-only controls hide for Nemotron, and confirm the Preferences tab no longer contains the moved controls. No Meeting was queued for this check.

### Review (2026-09-25)

Executor: Codex `gpt-6-luna`. At first it stopped on the STOP condition "plan
022 is not DONE". The condition was rewritten to what it protects, namely
that plan 022's backend is on this branch, and the run was resumed. The
reviewer fixed the following before committing:

- The Diarizer cards used a new text badge ("Ready"/"Degraded"/"Blocked")
  whose styles were copied from `engineMetadata.ts`, while decision 4 asks for
  the Preset look. The status dot is now `engineHealthDot` in
  `utils/engineHealth.ts`. `PresetTab` uses it in place of its inline
  conditional, and the Diarizer cards share the Preset card layout: radio,
  dot, ⚠️ summary, and a "Health checks" disclosure. `DiarizerOption` gains
  `checks`, which the backend already returns.
- The HF token copy said "Required for speaker diarization", which is no
  longer true for Nemotron. It now says pyannote downloads its gated models
  with it.

Verification by the reviewer: `npm run build` passes; `npm test` has 40
passed; the backend suite has 370 passed, 20 skipped. Revert-proof: making
the payload drop the threshold for Nemotron fails "keeps the stored threshold
while Nemotron is selected", and restoring the payload makes it pass. Step 5,
the manual check, is pending with the user.

Step 5, 2026-09-25: the user selected Nemotron in the tab and saved. The choice persisted (`GET /api/settings` returned `diarization.engine == "nemotron-3-diarization"`, with the stored 0.55 clustering threshold kept), and the next Meeting was diarized with it.
