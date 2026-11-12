# Plan 032: Review Notes: model, API, CLI and operator skill

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report; do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat d9dea5e..HEAD -- models/ api/ meeting_store.py main.py transcriber_cli/ GLOSSARY.md .claude/skills/transcriber-operator/SKILL.md`
> Any output is a STOP condition until you have compared it against the excerpts below.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: MED (new table and routes that call the existing edit routes)
- **Depends on**: 025, 027, 028, 029–031 (all DONE)
- **Category**: feature
- **Planned at**: commit `d9dea5e`, 2026-10-09
- **Source**: `.scratch/agent-operation/issues/01-review-notes.md`. Its design
  questions were answered by the user on 2026-10-09; the answers are the
  Decisions below. Plan 033 builds the Meeting page UI on top of this plan.

## Why this matters

When the coding agent reviews a Meeting (ADR-0010, skill `transcriber-operator`),
it finds passages only the user can settle: who a voice is, what a misheard
word was. Today those questions go to the chat. The user then has to find each
passage, play it, and type the answer back.

A **Review Note** moves that exchange into the Meeting. It is anchored at a
time range, so plan 033 can show it next to the Segment, with the audio one
click away. A suggestion the agent leaves can be accepted with one click, and
that acceptance is the user's confirmation. That is exactly what `--learn`
(Vocabulary) and `--save-profile` (Voice Profile) wait for today.

## Decisions (do not re-litigate)

1. **Anchor**: a time range (`start_time`, `end_time`, in seconds), never a
   Segment id. Segments are recreated on Reprocessing; a note keeps its range.
   A note is applied to the Segment that the existing tolerance rule picks at
   *accept* time (plan 028's `_claim_nearest`). It is not tied to a row.
2. **Kinds** (v1):
   - `comment`: descriptive, from the user or the agent;
   - `question`: from the agent, answered by the user;
   - `text`: the agent proposes new text for one Segment;
   - `speaker_name`: the agent proposes a name for a Speaker;
   - `speaker_move`: the agent proposes moving one Segment to another, or a
     new, Speaker;
   - `speaker_merge`: the agent proposes merging two Speakers.

   A Segment split is a later kind (issue 02).
3. **Accepting a `text` note teaches Vocabulary by default**, through the same
   path as `PUT /api/segments/{id}` with `learn: true`. `learn: false`
   ("accept without teaching") is available.
4. **Accepting a `speaker_name` note saves the Voice Profile by default**,
   through the same path as `POST /api/speaker-profiles/save-from-speaker`.
   `save_profile: false` is available. If the profile cannot be built (no
   audio, ffmpeg error), the rename still happens, and the response carries a
   `warning`.
5. **Authors**: `agent` and `user`, with `system` reserved for issue 08 and
   not used in v1. **The user only creates `comment` notes.** The user edits
   text directly when they want a change. Every other kind requires `author == "agent"`.
6. **Lifecycle**. A note is never deleted. Resolved notes stay as history.
   - `question`: `open` → `answered` (the user replies) → `done` (the agent
     acted). The user may also `dismiss` it.
   - `text` and `speaker_*`: `open` → `accepted` or `dismissed`.
   - `comment` (either author): `open` → `done`, optionally with a `reply`
     from whoever closes it.
7. **Export**: only the JSON export carries the notes, all of them with their
   status. The other formats are unchanged.
8. **Glossary name**: **Review Note**. The UI may say "Review" or "Nota de
   revisão".

## Current state

- `models/__init__.py` re-exports every model in `__all__` (Meeting, Speaker,
  Segment, Job, SpeakerProfile, VocabularyEntry). `database.init_db` runs
  `Base.metadata.create_all`, which creates a *new table* on an existing
  database too, and then `migrations.runner.upgrade`. A new table needs no
  migration. A new column on an existing table would need one (see migration 2).
- `models/segment.py` is the style exemplar: `uuid` string id,
  `Mapped[...] = mapped_column(...)`, `ForeignKey("meetings.id", ondelete="CASCADE")`, `to_dict()`.
- `models/meeting.py` `Meeting.to_dict(include_segments=True)` adds
  `speakers`, `segments`, `overlaps`. `GET /api/meetings/{id}` returns that.
  The Meeting page and the CLI's `load_meeting` read it.
- `meeting_store._claim_nearest(records, spans) -> {span_index: payload}`
  pairs `(start, end, payload)` records with the nearest span within
  `EDIT_TIME_TOLERANCE` (1.5 s), one-to-one.
- Edit routes are plain functions you may call directly with a `db` session.
  Each calls `require_editable`, commits, and calls
  `jobs.notify_meeting_changed`:
  - `api/segments.py`: `update_segment_text(segment_id, UpdateSegmentTextRequest(text, learn), db)`
    and `update_segment_speaker(segment_id, UpdateSegmentSpeakerRequest(speaker_id), db)`;
  - `api/speakers.py`: `update_speaker(speaker_id, UpdateSpeakerRequest(display_name=...), db)`,
    `merge_speakers(MergeSpeakersRequest(source_id, target_id), db)`, and
    `add_speaker(meeting_id, AddSpeakerRequest(display_name), db)` on
    `meeting_speakers_router`, which creates a `MANUAL_n` Speaker;
  - `api/speaker_profiles.py`: `save_profile_from_speaker(SaveFromSpeakerRequest(speaker_id, meeting_id, name), db)`.
    It raises `HTTPException` on missing audio or Segments.
- `api/export.py` `_export_json(meeting, segments)` builds
  `{"meeting", "speakers", "segments"}`.
- CLI:
  - `transcriber_cli/main.py` has `cmd_*` functions, `emit(args, data, lines)`,
    the parser built in one function (look for `add_parser`), and
    `load_meeting`;
  - handles live in `transcriber_cli/handles.py`
    (`resolve_meeting` / `resolve_segment` / `resolve_speaker`; `MIN_PREFIX = 4`);
  - rendering lives in `transcriber_cli/render.py` (`clock`, `segment_line`).
- Tests:
  - API tests use the `db_session` fixture in `tests/conftest.py` with
    `TestClient(app)`; follow `tests/test_meeting_api.py`;
  - CLI tests are in `tests/test_transcriber_cli.py` and use a TestClient
    transport. Read how they build `Api`.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Focus | `uv run pytest -q tests/test_review_notes.py tests/test_transcriber_cli.py` | all pass |
| Gate | `uv run pytest -q` (repo root) | 0 failures |
| Frontend gate | `npm test` in `frontend/` | all pass (unchanged) |

## Scope

**In scope**:
- `models/review_note.py` (create), `models/__init__.py`, `models/meeting.py` (`to_dict` key)
- `api/review_notes.py` (create), `main.py` (one `include_router` per new router)
- `meeting_store.py` (one public helper)
- `api/export.py` (`_export_json` key)
- `transcriber_cli/main.py`, `transcriber_cli/handles.py`, `transcriber_cli/render.py`
- `tests/test_review_notes.py` (create), `tests/test_transcriber_cli.py`
- `GLOSSARY.md` (one entry), `README.md` (route rows, CLI lines),
  `.claude/skills/transcriber-operator/SKILL.md`
- `.scratch/agent-operation/issues/01-review-notes.md` (status line)

**Out of scope**:
- The frontend (plan 033).
- Turning Vocabulary Corrections into notes (issue 08, later).
- Split (issue 02).
- Any change to the existing edit routes' behavior.

## Git workflow

- Branch `advisor/032-review-notes`. Commits per step, e.g.
  `feat(review-notes): model and Meeting payload`.
- Do not push.

## Steps

Test first for every step: the new test fails before the change. Show the red run.

### Step 1: Model

`models/review_note.py`, table `review_notes`:

| column | type | notes |
|---|---|---|
| `id` | String PK, uuid4 default | |
| `meeting_id` | FK `meetings.id`, `ondelete="CASCADE"`, indexed | |
| `start_time`, `end_time` | Float, not null | |
| `author` | String, not null | `agent` / `user` (`system` reserved) |
| `kind` | String, not null | one of the 6 kinds |
| `body` | Text, not null | the question, comment or rationale |
| `payload` | JSON, nullable | kind-specific, see Step 3 |
| `status` | String, not null, default `open` | `open`/`answered`/`accepted`/`dismissed`/`done` |
| `answer` | Text, nullable | the user's answer to a question |
| `reply` | Text, nullable | the closing reply on a comment or answered question |
| `created_at`, `resolved_at` | DateTime | `resolved_at` is set on accepted/dismissed/done |

Add `relationship` on `Meeting` with `cascade="all, delete-orphan"`, so
deleting a Meeting deletes its notes. Order notes by `start_time`. Add
`to_dict()` that returns every column; datetimes go out as ISO strings.

Add `ReviewNote` to `models/__init__.py`. Add
`d["review_notes"] = [n.to_dict() for n in self.review_notes]` in
`Meeting.to_dict(include_segments=True)`.

Notes are **not** copied to a duplicate. The duplicate route copies named
fields only, so this needs no code; a test pins it
(`test_duplicating_a_meeting_does_not_copy_notes`).

**Verify**: new tests:
- `test_meeting_payload_lists_review_notes`;
- `test_deleting_a_meeting_deletes_its_notes`;
- `test_fresh_database_has_review_notes_table`: run `init_db` on a temp
  SQLite file, following `tests/test_database_sqlite.py`.

### Step 2: Segment lookup helper

In `meeting_store.py` add:

```python
def segment_for_range(db, meeting_id, start, end):
    """The Segment a time range points at now: the nearest within EDIT_TIME_TOLERANCE, or None."""
```

Implement it with `_claim_nearest([(start, end, None)], spans)` over the
Meeting's Segments, ordered by `order`.

**Verify**: unit tests. An exact range returns its Segment. A range shifted
by 1 s returns the same Segment. A range 5 s away returns `None`. With two
neighbours, the nearer one wins.

### Step 3: Create, list, answer, close and dismiss routes

New `api/review_notes.py` with two routers, mirroring
`api/speakers.py`'s two-router pattern: `meeting_notes_router`
(prefix `/api/meetings`) and `router` (prefix `/api/notes`). Register both
in `main.py`.

- `POST /api/meetings/{meeting_id}/notes`. The body is
  `{start_time, end_time, kind, body, author, payload?}`.
  - Validation:
    - the Meeting must exist (404);
    - `start_time <= end_time` (400);
    - `kind` and `author` must be known (400);
    - `author == "user"` requires `kind == "comment"`
      (400 "a user note is a comment");
    - `body` must not be blank (400).
  - Payload by kind:
    - `text` requires `{"expected_text": str, "proposed_text": str}`. A
      Segment must exist for the range (`segment_for_range`, else 400 "no
      Segment at this range"), and `expected_text` must equal that
      Segment's current `text` (400 otherwise).
    - `speaker_name` requires `{"label": str, "name": str}`. The label must
      be a Speaker of the Meeting (400).
    - `speaker_move` requires `{"target_label": str}` **or**
      `{"new_name": str}`, and a Segment for the range.
    - `speaker_merge` requires `{"source_label", "target_label"}`, both
      existing and different.
    - `comment` and `question` take no payload.
  - Creating a note is allowed while the Meeting is PROCESSING: it changes no
    Segment. Call `jobs.notify_meeting_changed`. Return `note.to_dict()` with
    status 201 if the codebase uses 201 for creates; otherwise follow
    `add_speaker`'s convention.
- `GET /api/meetings/{meeting_id}/notes?status=` takes `open`, `answered`,
  `resolved` (= `accepted`/`dismissed`/`done`) or `all` (the default).
  Results are ordered by `start_time`. An unknown `status` is a 400.
- `POST /api/notes/{id}/answer {answer}` works only on an `open` `question`;
  otherwise 409. It sets `status="answered"` and `answer`.
- `POST /api/notes/{id}/done {reply?}` works on an `answered` question or an
  `open` comment; otherwise 409. It sets `status="done"`, `reply` and
  `resolved_at`.
- `POST /api/notes/{id}/dismiss` works on an `open` note of any kind except a
  comment (comments are closed with `done`), and on an `answered` question;
  otherwise 409. It sets `status="dismissed"` and `resolved_at`.
- Every mutating route returns 404 for a missing note and calls
  `notify_meeting_changed` after its commit.

**Verify**: one test per validation and per transition, including the 409s.
Name them by behavior, e.g. `test_a_user_note_must_be_a_comment`.

### Step 4: Accept

`POST /api/notes/{id}/accept {learn: bool = True, save_profile: bool = True}`.
It works only on an `open` note of kind `text` or `speaker_*`; otherwise 409.
`require_editable` applies, so a PROCESSING Meeting gets a 409. The apply step
calls the existing route functions, so behavior stays identical to a manual
edit:

- `text`:
  - `seg = segment_for_range(...)`; `None` → 409 "the passage no longer
    matches a Segment".
  - `seg.text != payload["expected_text"]` → 409 "the Segment changed since
    the suggestion".
  - Otherwise `update_segment_text(seg.id, UpdateSegmentTextRequest(text=proposed, learn=req.learn), db)`.
- `speaker_name`:
  - Find the Speaker by `(meeting_id, label)`; missing → 409.
  - Call `update_speaker(...display_name=name...)`.
  - If `save_profile`, call `save_profile_from_speaker(...)` inside
    `try/except HTTPException as e`. On failure, set
    `warning = f"Voice Profile not saved: {e.detail}"`.
- `speaker_move`:
  - Find the Segment as for `text` (409 if missing).
  - The target is the Speaker by `target_label` (409 if missing) or, with
    `new_name`, `add_speaker(meeting_id, AddSpeakerRequest(display_name=new_name), db)`.
  - Then call `update_segment_speaker(seg.id, ...)`.
- `speaker_merge`: resolve both labels (409 if missing) and call
  `merge_speakers(...)`.

Then set `status="accepted"` and `resolved_at`, commit, notify, and return
`{"note": note.to_dict(), "warning": warning_or_None}`.

**Verify**: tests.
- One per kind for the happy path. Assert the effect through the API:
  - Segment text changed, and the VocabularyEntry learned (for `text`);
  - `learn=False` teaches nothing;
  - the Speaker is renamed;
  - the Segment moved, including to a `new_name` Speaker;
  - the merge happened.
- The `speaker_name` test monkeypatches
  `api.review_notes.save_profile_from_speaker`, or the module path you
  import it through, to record its call. `save_profile=False` skips the
  call, and a raised `HTTPException(404, ...)` yields a `warning` while the
  rename persists.
- Error paths: a Segment changed since the suggestion gives 409, a resolved
  note gives 409, and a PROCESSING Meeting gives 409.

### Step 5: JSON export

In `_export_json`, add `"review_notes": [n.to_dict() for n in meeting.review_notes]`.

**Verify**: a test asserts the key and one note in the JSON export. Other
formats are unchanged, and the existing export tests pass.

### Step 6: CLI

Note handles: a full note id or a unique prefix of 4 or more characters,
resolved from the Meeting's `review_notes` (`resolve_note` in `handles.py`,
same style as `resolve_speaker`). A Segment-anchored command uses that
Segment's `start_time`/`end_time` as the range.

| Command | Does |
|---|---|
| `notes M [--status open\|answered\|resolved\|all]` | one line per note: `n:<id8> #<order or ?> <clock> <kind>/<status> <author>: <body>`, plus `-> <proposed_text>`, `-> <name>`, `answer: ...` or `reply: ...` when present. `#?` means no Segment at the range now. Default `all`. |
| `ask M #N "question"` | creates a `question` (author `agent`) |
| `note M #N "comment"` | creates a `comment` (author `agent`) |
| `suggest M #N "new text" --why "..."` | `text` note; `expected_text` is the Segment's current text; `body` is `--why` (required) |
| `suggest-name M SPEAKER NAME --at #N --why "..."` | `speaker_name`; range from `--at` (the evidence Segment) |
| `suggest-move M #N SPEAKER\|new:NAME --why "..."` | `speaker_move` |
| `suggest-merge M SOURCE TARGET --at #N --why "..."` | `speaker_merge` |
| `close M NOTE [--reply "..."]` | `done` |

There is no `accept` command. Accepting is the user's act, on the page
(plan 033). Add `render.note_line(note, segments)`.

**Verify**: CLI tests, one per command, through the TestClient transport,
asserting the stored note. For `notes`, assert the line format and the
`--status` filter.

### Step 7: Docs and skill

- `GLOSSARY.md`: add a **Review Note** entry in the section about the
  transcript or a new "Reviewing" subsection, following the file's format
  (bold term, definition, `_Avoid_:` line). Suggested definition: "A
  question, comment or suggestion anchored at a time range of a Meeting,
  left by the agent or the user for the other to settle. Accepting a
  suggestion is the user's confirmation." `_Avoid_: comment (bare),
  annotation, flag`.
- `README.md`: add route rows for the new routes and CLI lines for `notes`
  and `suggest`.
- **Invoke `writing-for-agents` before editing SKILL.md.** Change the skill
  so that:
  - Phase 3 and Phase 4: when the evidence is not enough to act, leave a
    Review Note instead of a chat question. Use `suggest-name`,
    `suggest-move` or `suggest-merge` when a concrete proposal exists, `ask`
    otherwise, and `suggest` for a text fix the transcript does not prove.
    Direct `edit`/`rename` remains for what the transcript proves.
  - **Phase 0 (new, before Preflight's done-line) for an existing Meeting:**
    `notes M --status answered` and the open user comments (`notes M --status open`,
    author `user`) are the user's replies. Act on each, then `close` it with
    a short `--reply`.
  - Hand off: tell the user how many notes are open and that the Meeting
    page shows them (after plan 033). Keep the chat summary short.
  - Learning: accepting a `suggest` on the page teaches Vocabulary, so
    prefer `suggest` over asking for confirmation in chat.
- `.scratch/agent-operation/issues/01-review-notes.md`: set the status to
  `ready-for-agent (plans 032, 033)` and summarize the decisions.

**Verify**: `uv run pytest -q` exits 0; `npm test` in `frontend/` passes.

## Done criteria

- [ ] `uv run pytest -q` exits 0; the new tests from Steps 1–6 were red first
- [ ] `rg -n "review_notes" models/meeting.py api/export.py` matches both
- [ ] `uv run python -m transcriber_cli --help` lists `notes ask note suggest suggest-name suggest-move suggest-merge close`
- [ ] GLOSSARY has **Review Note**; SKILL.md was edited after invoking `writing-for-agents`
- [ ] `plans/README.md` row for 032 updated

## STOP conditions

- Drift beyond the excerpts.
- Calling a route function directly fails because it depends on FastAPI
  machinery other than `db` (e.g. `Depends` defaults evaluated). Report it.
  Do not reimplement the edit logic.

(Checked at planning time: the duplicate route in `api/meetings.py` copies
named fields only, so it does not copy notes. `api/speaker_profiles.py` is
already imported by `main.py`, so importing it from `api/review_notes.py`
loads nothing new.)

## Maintenance notes

- Issue 08 will add `author="system"` notes for Vocabulary Corrections. Keep
  `author` validation in one place, so that is a one-line change.
- A note keeps its time range forever. If Re-diarize moves Segment
  boundaries more than 1.5 s, `#?` shows in the CLI and accept returns 409.
  That is intended: the passage changed.
