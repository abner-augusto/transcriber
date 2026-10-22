# 02 - Settings Screen for the Folders Searched for a Moved Original

**Source:** plan 046 (`plans/README.md`, row 046: "no Settings screen for `source_roots`
yet"); ADR-0012. Split from ticket 01 on 2026-10-22.

**What to build:** A section in Settings -> Preferences to see and change the two
Preferences that tell the app where to look for an original recording that moved:

- `source_roots`: the list of folders searched (absolute paths, empty by default). Add a
  folder, remove one. The server already drops a relative path and a duplicate, so the page
  shows what the server kept after saving.
- `source_search_depth`: how many levels below each root the search walks (default 3; a
  file in the root is level 0).

Today the only way to set them is `PUT /api/settings/preferences` by hand, so a user whose
triage moves recordings out of the inbox cannot make the app find them again from the page.

**Why:** a rerun (Re-diarize, Full reprocess, Duplicate) of a dual-track Meeting reads its
original through the Source Reference. When the file moved, the app searches these folders
before answering 409 (ADR-0012). With the folders set once, the user stops running
`set M --source NEWPATH` after every move.

**Blocked by:** none.

**Status:** ready-for-agent

**Acceptance criteria:**
- [ ] Settings -> Preferences shows the current folders and the depth, read from
      `GET /api/settings/preferences`.
- [ ] Adding a folder and removing one are saved with `PUT /api/settings/preferences`
      (`source_roots` as the whole list), and the list shown afterwards is the one the
      server returned.
- [ ] The depth accepts a whole number from 0 up; a blank or invalid value is refused on the
      page and never sent.
- [ ] A relative path is refused on the page with a message ("absolute path"), as the
      server would drop it.
- [ ] The payload builder is a pure function with a vitest test, like
      `frontend/src/components/settings/preferencesPayload.ts`.
- [ ] README (Storage paragraph) says the folders can be set on the Settings page.
- [ ] `npm test` in `frontend/` and `pytest` from the repo root pass, and the output is read.

**Notes:**
- Backend is done: `preferences.py` (`source_roots`, `source_search_depth` and their
  validation in the patch) and `services/source_reference.py` (the search). This ticket is
  frontend only; it needs no migration.
- The browser cannot browse the disk for a folder, so the field is a text input for the
  absolute path.
