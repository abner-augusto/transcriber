# Plan 011: Split SettingsDialog and HomePage without changing behavior

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 40b455a..HEAD -- frontend/src/components/SettingsDialog.tsx frontend/src/pages/HomePage.tsx frontend/src/App.tsx frontend/src/api.ts frontend/src/types.ts`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: L
- **Risk**: HIGH
- **Depends on**: none
- **Category**: tech-debt
- **Planned at**: commit `40b455a`, 2026-09-17

## Why this matters

`SettingsDialog.tsx` (~790 lines) owns preset CRUD, engine-specific form
fields, preferences, HF token, voice profiles, and vocabulary profiles.
`HomePage.tsx` (~761 lines) owns the meeting list, search, inline rename,
and the entire single/dual-track upload dialog. Both files mix independent
state machines. Edits to presets regularly risk breaking upload, and the
other way around. This plan moves code into sibling modules with **no
visual or API change**.

## Current state

- `frontend/src/components/SettingsDialog.tsx:16-101` — `ENGINE_METADATA`
  + `DEFAULT_ENGINE_META`. Used for badges, placeholders, and which fields
  the add/edit form shows.
- `frontend/src/components/SettingsDialog.tsx:102-245` — load/save handlers
  for presets and preferences.
- `frontend/src/components/SettingsDialog.tsx:332+` — modal shell, tab
  switch `presets | preferences`, then a large JSX tree.
- `frontend/src/pages/HomePage.tsx:12-17` — `STATUS_LABELS` is
  `uploaded | processing | completed | failed`. Live-recording keys are
  already gone; do not restore them.
- `frontend/src/pages/HomePage.tsx:125-173` — `handleUpload` / `resetDialog`.
- `frontend/src/pages/HomePage.tsx:263+` — `{showUpload && (...)}` dialog
  JSX through the dual-track file pickers, vocabulary, preset select, and
  submit.
- HomePage no longer has a LIVE badge; do not add one.
- `frontend/src/App.tsx:36` — `{showSettings && <SettingsDialog onClose={...} />}`.
  Keep this import path (`../components/SettingsDialog`).
- Tests: none for these components. Do not add jsdom. Optional: unit-test
  `engineMetadata` lookups like `engineHealth.test.ts`.

Repo conventions: Tailwind class strings stay as they are (copy, do not
restyle). Named default export for page/dialog components. Vitest only for
pure helpers.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Frontend tests | `npm test` (cwd `frontend`) | all pass |
| Frontend build | `npm run build` (cwd `frontend`) | exit 0 |
| Line-count check | see Done criteria | SettingsDialog and HomePage below caps |

## Scope

**In scope**:

- `frontend/src/engineMetadata.ts` (create) — move `ENGINE_METADATA` +
  `DEFAULT_ENGINE_META` + a `engineMeta(engine: string)` getter
- `frontend/src/engineMetadata.test.ts` (create) — getter fallback
- `frontend/src/components/settings/PresetTab.tsx` (create)
- `frontend/src/components/settings/PreferencesTab.tsx` (create)
- `frontend/src/components/SettingsDialog.tsx` — shell only after the split
- `frontend/src/components/UploadDialog.tsx` (create)
- `frontend/src/pages/HomePage.tsx` — list/search/rename; render
  `UploadDialog` when `showUpload`

**Out of scope**:

- Any CSS/Tailwind restyle, copy rewrite, or layout change.
- Reintroducing `recording` / `finalizing` / live-session UI (already removed).
- `MeetingPage.tsx` (Plan 009).
- Zustand redesign.
- New npm dependencies, jsdom, Testing Library.
- Backend, `engines/`.
- Extracting `STATUS_LABELS` unless it is a pure cut-paste into
  `HomePage` still.

## Git workflow

- Branch: `advisor/011-split-settings-and-upload`
- Commits, in order:
  1. `refactor(frontend): extract engine metadata table`
  2. `refactor(frontend): split SettingsDialog tabs`
  3. `refactor(frontend): extract UploadDialog from HomePage`
- Do NOT push unless instructed.

## Steps

### Step 1: Move ENGINE_METADATA with a test

Cut `EngineMetadata`, `ENGINE_METADATA`, and `DEFAULT_ENGINE_META` from
`SettingsDialog.tsx` into `frontend/src/engineMetadata.ts`. Export
`engineMeta(engine: string)` that returns `ENGINE_METADATA[engine] || DEFAULT_ENGINE_META`.

`SettingsDialog.tsx` imports `engineMeta` (and the map if badges still
need it). Behavior of placeholders/badges must be identical.

Test `engineMeta("vibevoice").supportsAligner === true`,
`engineMeta("unknown-engine").modelPlaceholder` equals the default.

**Verify**: `npm test` and `npm run build` in `frontend` → pass.

### Step 2: Split Settings tabs

Create `frontend/src/components/settings/PresetTab.tsx` with the presets
list, add/edit form, default-radio, delete, and all preset-related state
that currently lives in SettingsDialog (`showAddPreset`, `editingPresetId`,
`newName`, `newEngine`, …, `handleSavePreset`, …).

Props:

```ts
interface PresetTabProps {
  settings: ModelSettings;
  onSettings: (s: ModelSettings) => void;
}
```

Create `PreferencesTab.tsx` with vocabulary/default vocab, profiles toggle,
HF token field, clustering threshold, switch penalty, speaker profile list,
learned vocab, vocabulary profiles. It owns `loadPreferences` /
`handleSave` for the preferences tab.

`SettingsDialog.tsx` after this step should:

- keep the overlay, title, tab switcher, close-on-backdrop
- load `getModelSettings` once
- render `PresetTab` or `PreferencesTab`
- keep the footer Save button **only if** today's UI has a shared Save
  that writes preferences. If Save is already inside the preferences
  handlers (`handleSave` when `tab === "preferences"`), move it with
  PreferencesTab and do not invent a new footer.

Target: `SettingsDialog.tsx` under **220 lines**.

Do not change `App.tsx` import path.

**Verify**: `npm run build` → exit 0. Manually sanity-check is not
available to the executor; rely on build + no class-string edits.

### Step 3: Extract UploadDialog

Create `frontend/src/components/UploadDialog.tsx`.

Props:

```ts
interface UploadDialogProps {
  onClose: () => void;
  onCreated: (meetingId: string) => void;
}
```

Move into it: all upload/dual-track/file/title/participants/vocab/preset/
profile state, `handleUpload`, `resetDialog`, the dialog JSX (from the
`showUpload &&` block). Call `onCreated(meeting.id)` instead of
`navigate(...)` so HomePage still owns routing:

```tsx
{showUpload && (
  <UploadDialog
    onClose={() => setShowUpload(false)}
    onCreated={(id) => navigate(`/meetings/${id}`)}
  />
)}
```

HomePage keeps: meetings list, search, rename, delete, `STATUS_LABELS`.

Target: `HomePage.tsx` under **400 lines**, `UploadDialog.tsx` holds the
dialog.

**Verify**: `npm run build` → exit 0. `npm test` → pass.

### Step 4: Line-count gates

From repo root (PowerShell):

```powershell
@(
  @{f='frontend/src/components/SettingsDialog.tsx'; max=220},
  @{f='frontend/src/pages/HomePage.tsx'; max=400}
) | ForEach-Object {
  $n = (Get-Content $_.f).Count
  if ($n -gt $_.max) { throw "$($_.f) has $n lines (max $($_.max))" }
  "$($_.f) $n"
}
```

**Verify**: command prints both files and does not throw.

## Test plan

- `frontend/src/engineMetadata.test.ts` only.
- Pattern: `frontend/src/utils/engineHealth.test.ts`.
- No component snapshot tests.
- Verification: `npm test` in `frontend`.

## Done criteria

- [ ] `npm test` in `frontend` exits 0
- [ ] `npm run build` in `frontend` exits 0
- [ ] `SettingsDialog.tsx` ≤ 220 lines
- [ ] `HomePage.tsx` ≤ 400 lines
- [ ] `App.tsx` still imports `./components/SettingsDialog`
- [ ] `git diff frontend/package.json` empty
- [ ] No Tailwind class strings rewritten (copy-paste only). If a diff
      shows class churn on unchanged elements, revert that hunk.
- [ ] `STATUS_LABELS` still has only uploaded/processing/completed/failed
- [ ] No files outside the in-scope list are modified
- [ ] `plans/README.md` status row for 011 updated

## STOP conditions

- Current-state excerpts no longer match (especially if HomePage upload
  JSX was already extracted).
- You need a new dependency or a CSS file.
- Split seems to require lifting state into Zustand. Do not. Keep state
  local to the extracted component.
- Settings save-button behavior is unclear after reading the file — STOP
  rather than inventing a second Save.
- Line-count caps cannot be met without deleting features. STOP.

## Maintenance notes

- Reviewer should diff with whitespace ignored and reject class/copy
  changes.
- Live-recording UI is already gone; keep it gone.
- Engine badge copy lives in `engineMetadata.ts`; adding an Engine means
  a Preset JSON **and** a row there — same as today, just not inside the
  dialog component.
