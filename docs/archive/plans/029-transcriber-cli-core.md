# Plan 029: A stdlib CLI lets an agent run and read Meetings in compact text

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report; do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat c5cc40a..HEAD -- api/ models/ tests/conftest.py tests/test_meeting_api.py`
> Plans 025–028 are expected to have changed `api/` and `models/segment.py`.
> Read the route signatures you call (listed under "Current state") in the live
> code and use what is there. If a route listed here is missing, STOP.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW (a new client package; the app is not changed)
- **Depends on**: plan 024 (ADR-0010; root gate), plan 026 (`/words` route)
- **Category**: direction, dx
- **Planned at**: commit `c5cc40a`, 2026-10-09
- **Source**: agent-friendliness audit, 2026-10-09

## Why this matters

ADR-0010 lets a coding agent operate this app. Through raw HTTP that is
expensive and error-prone: ~25 routes, UUIDs everywhere, and
`GET /api/meetings/{id}` returns every Segment, Speaker, and overlap as verbose
JSON (a 2-hour Meeting is thousands of lines in an agent's context). An agent
also cannot wait for a Job except by polling by hand. A small CLI fixes all
three. It gives short handles (`#142` for a Segment, `SPEAKER_01` or a name for
a Speaker, an 8-character prefix for a Meeting), one line per Segment, and a
blocking `wait`. It uses only the standard library and only HTTP, so it starts
instantly (no torch import), works with any agent (Claude Code, Codex, a local
model), and never touches the database behind the app's back.

This plan builds the read and lifecycle half. Plan 030 adds the edit commands,
`suspects`, and the operator skill.

## Current state

The app runs at `http://127.0.0.1:8000` (`start.ps1`, `start.sh`; the
uvicorn port is 8000). Routes the CLI calls, all under `/api`:

| Route | Returns |
|---|---|
| `GET /health` | `{"status": "ok"|"degraded", "database": ..., ...}` |
| `GET /meetings` | list of Meeting dicts with `id, title, status, duration, speaker_count, segment_count, created_at, participants, vocabulary, preset_id` |
| `POST /meetings` (multipart) | form fields `title` (required), `file` (required), `system_file`, `min_speakers`, `max_speakers`, `vocabulary`, `participants`, `preset_id` → Meeting dict |
| `GET /meetings/{id}` | Meeting dict + `speakers`, `segments`, `overlaps` |
| `POST /meetings/{id}/process` | Job dict (+ `engine_health`); 409 when processing or blocked |
| `POST /meetings/{id}/rediarize` · `/reidentify` · `/reapply-vocabulary` | Job dict; 400 when never processed; 409 when processing |
| `GET /meetings/{id}/jobs` | Job dicts, newest first: `id, job_type, status (pending|running|completed|failed), progress, current_step, error` |
| `GET /meetings/{id}/words?start=&end=` | Word dicts `start, end, text, confidence, alignment_score` (plan 026) |
| `GET /meetings/{id}/export?format=srt|vtt|txt|json|md|docx|pdf` | file body |

Segment dict keys (`models/segment.py` `to_dict`): `id, meeting_id,
speaker_id, speaker_label, speaker_name, speaker_color, start_time, end_time,
text, original_text, order, is_edited, confidence, corrections`, plus
`speaker_edited` after plan 028. Speaker dict keys: `id, meeting_id, label,
display_name, color, identified_by, confidence, total_speaking_time,
segment_count`.

Errors are FastAPI's `{"detail": ...}`. `detail` is usually a string, but the
health-check 409s send `{"detail": {"message": str, "health": {...}}}`.

Repo conventions:
- Flat top-level Python packages (`engines/`, `jobs/`, `transcript/`). Dev
  scripts use `argparse` (`scripts/engine_doctor.py`).
- Tests: `tests/test_meeting_api.py` defines the `db_session` fixture (in-memory
  SQLite, `InlineJobRunner`, `InProcessBus`, `get_db` override) and uses
  `TestClient(app)`.
- Glossary terms in help text and output: Meeting, Segment, Speaker, Word,
  Job, Reprocessing, Vocabulary, Preset.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| CLI tests | `uv run pytest -q tests/test_transcriber_cli.py` | all pass |
| Backend gate | `uv run pytest -q` | 0 failures |
| Smoke | `uv run python -m transcriber_cli --help` | usage text, exit 0 |

## Scope

**In scope**:
- `transcriber_cli/__init__.py`, `__main__.py`, `client.py`, `handles.py`, `render.py`, `main.py` (create)
- `tests/conftest.py` (receive the moved `db_session` fixture)
- `tests/test_meeting_api.py` (remove the fixture body it no longer owns)
- `tests/test_transcriber_cli.py` (create)
- `README.md` (one short "Command line" section)

**Out of scope**: every app module (`api/`, `models/`, `jobs/`, …). The CLI
must not import them. Edit commands and `suspects` belong to plan 030.

## Git workflow

- Branch: `advisor/029-cli-core`; commits like `feat(cli): read and run Meetings from the command line`.
- Do not push.

## Steps

### Step 1: Share the API fixture

Move the `db_session` fixture and the imports it needs from
`tests/test_meeting_api.py` to `tests/conftest.py`, unchanged.

**Verify**: `uv run pytest -q tests/test_meeting_api.py` → same pass count as before.

### Step 2: HTTP client (`transcriber_cli/client.py`)

```python
DEFAULT_URL = "http://127.0.0.1:8000"

class ApiError(Exception):
    def __init__(self, status: int, message: str): ...

class Api:
    def __init__(self, base_url: str | None = None, transport=None):
        """base_url defaults to $TRANSCRIBER_URL, then DEFAULT_URL.
        transport(method, url, headers, body) -> (status, bytes); defaults to urllib."""
    def get(self, path, **params) -> object
    def post(self, path, json=None) -> object
    def put(self, path, json=None) -> object
    def delete(self, path) -> object
    def raw(self, path, **params) -> bytes          # export downloads
    def upload(self, path, fields: dict[str, str], files: dict[str, str]) -> object
```

- `path` starts with `/api/...`. JSON bodies are UTF-8 with
  `Content-Type: application/json`. Responses decode as JSON when the body is
  non-empty.
- Status ≥ 400 → `ApiError(status, message)`. `message` is `detail` when it
  is a string, `detail["message"]` when it is a dict, else the raw text.
- urllib connection refused → `ApiError(0, "Transcriber is not running at <url>. Start it with ./start.ps1 (Windows) or ./start.sh.")`.
- `upload` streams multipart/form-data without reading the file into memory.
  Build the body as an iterable of bytes (preamble, 1 MiB file chunks,
  epilogue) and compute `Content-Length` from the part sizes plus
  `os.path.getsize`. Boundary: `uuid.uuid4().hex`. Each file part needs
  `Content-Disposition: form-data; name="<field>"; filename="<basename>"` and
  `Content-Type: application/octet-stream`.
- The default transport uses `urllib.request.Request(url, data=body, method=..., headers=...)`
  with a 30 s timeout (none for `upload`).

### Step 3: Handles (`transcriber_cli/handles.py`)

- `resolve_meeting(api, handle) -> dict`: exact id; else a unique id prefix
  of ≥ 4 chars; else a case-insensitive exact title. Zero matches →
  `ApiError(404, "No Meeting matches '<h>'")`. Several →
  `ApiError(400, "'<h>' matches N Meetings: <id8 title>, ...")`.
- `resolve_segment(meeting: dict, handle) -> dict`: `"#12"` or `"12"` →
  the Segment whose `order` is 12.
- `resolve_speaker(meeting: dict, handle) -> dict`: exact `label`
  (`SPEAKER_01`, `HOST`, `MANUAL_1`), then case-insensitive `display_name`,
  then a unique id prefix. Ambiguity → `ApiError(400, ...)` listing candidates.

### Step 4: Rendering (`transcriber_cli/render.py`)

Plain ASCII, so it is safe in any Windows console:

- `clock(seconds) -> "MM:SS"` or `"H:MM:SS"`; `parse_clock("3:41") -> 221.0`
  (accepts `SS`, `MM:SS`, `H:MM:SS`, or plain seconds).
- `segment_line(seg) -> str`: `#<order> <clock(start)> <speaker_name or label or "?">: <text>`, followed by markers in this order when they apply:
  ` [edited]` if `is_edited`; ` [moved]` if `speaker_edited`; ` [conf 0.52]` if
  `confidence` is not None and `< 0.6` (the UI's low-confidence threshold,
  `TranscriptView.tsx`); ` [fixed: Galo->Garrah]` once per correction.
- `speaker_line(sp) -> str`: `<label> "<display_name>" by=<identified_by or "-"> segs=<n> time=<clock>`.
- `meeting_header(m) -> list[str]`: id (full), title, status, duration,
  participants, vocabulary — skip empty ones.

### Step 5: Commands (`transcriber_cli/main.py`, `__main__.py`)

`argparse` with subcommands. A global `--json` flag prints the raw API JSON
instead of text. `main(argv=None, api=None) -> int` so tests can inject an
`Api`. `ApiError` prints `error: <message>` to stderr and returns 1 (2 when
`status == 0`, i.e. the server is down).

| Command | Behavior |
|---|---|
| `health` | `GET /api/health`; prints `status` and any non-ok check |
| `list` | one line per Meeting: `id[:8] status clock(duration) speakers=N segments=N title` |
| `upload FILE --title T [--system FILE] [--participants S] [--vocabulary S] [--preset ID] [--min-speakers N] [--max-speakers N] [--process] [--wait]` | `POST /api/meetings`; prints the new id. `--process` then runs `process`; `--wait` (only with `--process`) then runs `wait` |
| `process M [--wait]` | `POST .../process`; with `--wait`, then runs `wait` |
| `reprocess M {rediarize,reidentify,reapply-vocabulary} [--wait]` | the matching POST |
| `wait M [--timeout SECONDS] [--interval 2]` | polls `GET .../jobs`. Prints `progress% step` when the step changes. Exit 0 when the newest Job is `completed`; exit 1 and print its `error` when `failed`; exit 3 on timeout (default: none) |
| `show M [--from T] [--to T] [--speaker S] [--limit N]` | header, blank line, speaker lines, blank line, Segment lines filtered by time overlap and Speaker |
| `speakers M [--unnamed] [--samples N]` | speaker lines. `--unnamed` keeps Speakers with `identified_by` null and label not `UNKNOWN`. `--samples N` (default 0; 3 with `--unnamed`) prints that Speaker's N longest Segments as indented Segment lines |
| `words M --from T --to T [--below C]` | `GET .../words`; one line per Word: `clock(start) <text.strip()> <confidence or "-">`; `--below` keeps confidence < C |
| `export M --format F [--out PATH]` | `raw(...)`; writes to `--out` or stdout (binary formats require `--out`) |

`__main__.py`: `from .main import main; raise SystemExit(main())`.

**Verify**: `uv run python -m transcriber_cli --help` lists every command above.

### Step 6: README

Add a "Command line" section after "Usage": two sentences on what the CLI is
for (scripting and agents, see ADR-0010), plus three example lines:
`uv run python -m transcriber_cli list`,
`... upload reuniao.m4a --title "Obra 12/10" --participants "Ana, Bruno" --process --wait`, and
`... show <id> --from 10:00 --to 15:00`.

**Verify**: each README example runs against a local app, or record "not run" in the outcome note.

## Test plan

`tests/test_transcriber_cli.py`, using `db_session` (now in conftest) and a
transport that forwards to `TestClient(app)`:

```python
def testclient_transport(client):
    def transport(method, url, headers, body):
        path = url.split("://", 1)[1].split("/", 1)[1]
        content = body if isinstance(body, (bytes, type(None))) else b"".join(body)
        r = client.request(method, "/" + path, content=content, headers=headers)
        return r.status_code, r.content
    return transport
```

Cases (seed Meetings/Speakers/Segments with `db_session`, as the API tests do;
capture output with `capsys`):

1. `list` prints the 8-char id and title.
2. Meeting handle: a unique prefix resolves; an ambiguous prefix exits 1 with "matches".
3. `show` renders `#0 00:00 Maria: Bom dia [conf 0.41]` for a Segment with confidence 0.41.
4. `show --from 1:00 --to 2:00` keeps only overlapping Segments.
5. `speakers --unnamed` lists the Speaker with `identified_by=None` and not the
   `voice_profile` one, with up to 3 sample lines.
6. `upload` sends multipart: monkeypatch `api.meetings.AudioService.probe_audio`
   to return `{"stream_count": 1, "channels": 1}`, upload a 10-byte `.wav` from
   `tmp_path`, and the Meeting exists with the given title and participants.
7. `wait` returns 0 for a completed Job, and 1 printing the error for a failed one
   (seed `Job` rows directly; `--interval 0`).
8. `words --below 0.5` prints only the low-confidence Word.
9. Unreachable server: an `Api` whose transport raises `ConnectionRefusedError`
   (map it to `ApiError(0, ...)` in the default transport, and test the mapping
   function directly) → exit code 2.
10. Pure: `parse_clock` and `clock` round-trip `"1:02:03"`.

## Done criteria

- [ ] `uv run pytest -q` exits 0 with ≥ 10 new tests
- [ ] `rg -n "^from (api|models|jobs|database|engines|tasks|transcript)|^import (api|models|jobs|database)" transcriber_cli/` → no match (stdlib + own modules only)
- [ ] `uv run python -m transcriber_cli --help` exits 0
- [ ] `plans/README.md` row for 029 updated

## STOP conditions

- A route in the table above is missing or has a different shape (especially
  `/words` from plan 026).
- `TestClient.request` cannot send a precomputed multipart body. Report it;
  do not add `httpx` or `requests` to the CLI.
- Moving `db_session` breaks another test module that defines its own fixture
  of the same name (`rg -n "def db_session" tests/`).

## Maintenance notes

- The CLI is a client of the HTTP API. When a route changes shape, the CLI
  test that exercises it fails first. Keep those tests end-to-end through
  `TestClient`.
- Output lines are an interface agents parse by eye. Change markers only
  together with plan 030's skill text.
