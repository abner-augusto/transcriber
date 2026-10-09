# Plan 024: The repo-root gate passes, the README matches the app, and ADR-0010 records agent operation

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report; do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat c5cc40a..HEAD -- pytest.ini pyproject.toml README.md docs/adr/`
> Any change in those paths since `c5cc40a` is a STOP condition until you have
> compared it against the excerpts below.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW (config and docs only)
- **Depends on**: none
- **Category**: dx, docs
- **Planned at**: commit `c5cc40a`, 2026-10-09
- **Source**: agent-friendliness audit, 2026-10-09; user decision "ADR novo,
  agente-agnóstico"

## Why this matters

`AGENTS.md` says a change is done when "`pytest` from the repo root" passes.
Today that command fails before running a single test: it collects
`bench/test_asr_aligner.py`, which imports `transformers`, a package that only
exists in an isolated Engine runtime. Every agent that follows the documented
gate hits a red error it did not cause. The README also still tells the user to
"Run **Actions**", a feature ADR-0002 deleted. And the user has decided to let
a coding agent (Claude Code, Codex, or a local agent) operate the app through
its HTTP API. That sends transcript text to whichever model the agent uses. ADR-0001
forbids the *app* from sending Meeting data anywhere. The decision needs its own
ADR, or the next audit will report the agent workflow as an ADR-0001 violation.

## Current state

- `pytest.ini` (whole file):

  ```ini
  [pytest]
  markers =
      model_load: opt-in smoke test that loads local Engine model artifacts
      model_inference: opt-in smoke test that runs inference over a local audio file
  ```

  No `testpaths`, so `pytest` walks the whole repo and collects `bench/test_*.py`.
- `pyproject.toml` has a second, ignored pytest config (pytest reads
  `pytest.ini` first and stops):

  ```toml
  [tool.pytest.ini_options]
  markers = [
      "model_load: loads locally installed speech models",
      "model_inference: runs local speech models against audio",
  ]
  ```
- Observed on 2026-10-09:
  - `uv run pytest -q -x` → `ERROR bench/test_asr_aligner.py ... ModuleNotFoundError: No module named 'transformers'`
  - `uv run pytest -q tests` → `372 passed, 20 skipped`
- `bench/test_*.py` files (`test_asr_aligner.py`, `test_cuda.py`, `test_qwen.py`,
  `test_qwen_stitch.py`) are manual GPU scripts, not part of the gate.
- `README.md` "Usage" section, step 8: `8. Run **Actions** (summarize, action items, etc.) from the sidebar`.
  Step 7 says "Click speaker names to rename, click segments to edit text".
- `README.md` "How it works", step 4: `**Diarization** — a **Diarizer** (pyannote 3.1, on the local GPU) turns the same audio into **Turns**`.
  Since plans 022/023 (ADR-0009) the Diarizer is selectable: pyannote Community-1
  or Nemotron 3 Diarization (see `main.py` `get_settings`).
- `README.md` "Prerequisites": `Hugging Face access to pyannote/speaker-diarization-3.1 for diarization`.
  Leave this line alone: it is about which weights the installer downloads. Do
  not check or change model ids.
- `docs/adr/` holds `0001`…`0009`. ADR format (from `0001-no-data-leaves-the-machine.md`):
  a `# Title` line, `**Status**: accepted`, prose, then `## Consequences`.
- ADR-0001 says: "no Meeting data — audio, transcripts, Words, or Voice Profile
  embeddings — is ever sent to a remote service. Every Engine runs locally."
  It also says "Cloud LLMs are out of scope" and "A local LLM is permitted".
- ADR-0002 lists what a reintroduced LLM feature *inside the app* must satisfy,
  including "Run locally (ADR-0001)" and "Not duplicate what Voice Profile
  matching already does well".

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Backend gate | `uv run pytest -q` (repo root) | `372 passed, 20 skipped` or more passed, 0 errors |
| Frontend gate | `npm test` in `frontend/` | `Tests 40 passed` or more |

## Scope

**In scope**:
- `pytest.ini`
- `pyproject.toml` (remove only the `[tool.pytest.ini_options]` table)
- `README.md` (the lines named in Steps 2–3 only)
- `docs/adr/0010-an-agent-may-operate-the-local-api.md` (create)

**Out of scope**:
- `bench/` — do not rename or delete the manual GPU scripts.
- `AGENTS.md` — plan 030 adds the operator pointer.
- ADR-0001 and ADR-0002 text — the new ADR refers to them; it does not edit them.

## Git workflow

- Branch: `advisor/024-truthful-gate`
- Conventional commits, matching `git log`: e.g.
  `fix(tests): collect only tests/ from the repo root`,
  `docs(adr): an agent may operate the local API`.
- Do not push.

## Steps

### Step 1: Collect only `tests/`

Add `testpaths = tests` to `pytest.ini` under `[pytest]`. Delete the whole
`[tool.pytest.ini_options]` table from `pyproject.toml`, including its
`markers` list, so only one pytest config remains.

**Verify**: `uv run pytest -q` from the repo root → ends with `passed`, no
`ERROR` lines, and a pass count of at least 372.

### Step 2: README usage matches the app

- Delete Usage step 8 (Actions) and renumber step 9 to 8.
- Change "How it works" step 4 to name the Diarizer generically:
  `4. **Diarization** — a **Diarizer** (pyannote or Nemotron 3 Diarization, chosen in Settings → Diarization, on the local GPU) turns the same audio into **Turns**`.

**Verify**: `rg -n "Actions|pyannote 3.1" README.md` → no match for `Actions`;
`pyannote 3.1` may remain only if it is in the Prerequisites line.

### Step 3: ADR-0010

Create `docs/adr/0010-an-agent-may-operate-the-local-api.md` with this content
(you may fix typos; do not change the decision):

```markdown
# An agent may operate the local API

**Status**: accepted

The user may hand a Meeting to a coding agent (Claude Code, Codex, or an agent
running a local model) that drives this app through its HTTP API: uploading and
processing Meetings, reading the transcript, naming Speakers, and correcting
Segments. The agent reads transcript text, and if its model is hosted, that text
leaves the machine.

This does not contradict ADR-0001. ADR-0001 constrains the app: no Engine, Job,
or route sends Meeting data anywhere, and that stays true. An agent is a client
the user chose to run, like copying an export into a chat. The app never calls
an agent, never ships an API key, and never depends on one.

## Consequences

- The agent interface is the HTTP API plus a stdlib-only CLI over it
  (`transcriber_cli`). Nothing in the app imports an LLM SDK.
- The CLI works the same against any agent, so a user who wants ADR-0001's
  guarantee end to end can run the workflow with a local model.
- Agent text edits do not teach Vocabulary by default: the agent cannot hear the
  audio, so its corrections are guesses until the user confirms them.
- Agent naming complements Voice Profile matching (ADR-0002, point 4): the agent
  names only the Speakers no Voice Profile matched, and saving a Voice Profile
  stays an explicit step so the next Meeting is named from the voice.
- ADR-0002 still governs any LLM feature built *into* the app.
```

**Verify**: `ls docs/adr/0010-an-agent-may-operate-the-local-api.md` → exists.

### Step 4: Full gate

**Verify**: `uv run pytest -q` → 0 errors; `cd frontend && npm test` → all pass.

## Test plan

No new tests: Step 1 changes collection, and the gate command itself is the
check.

## Done criteria

- [ ] `uv run pytest -q` from the repo root exits 0
- [ ] `rg -n "tool.pytest" pyproject.toml` → no match
- [ ] `rg -n "Run \*\*Actions" README.md` → no match
- [ ] `docs/adr/0010-an-agent-may-operate-the-local-api.md` exists
- [ ] `git status` shows only the in-scope files changed
- [ ] `plans/README.md` row for 024 updated

## STOP conditions

- After Step 1, a test under `tests/` fails that passed under
  `uv run pytest -q tests` before the change.
- `docs/adr/0010-*` already exists with a different decision.

## Maintenance notes

- A new manual script in `bench/` named `test_*.py` no longer breaks the gate,
  but a new real test placed outside `tests/` will be silently skipped.
- ADR-0010 is the record plans 029/030 point to; keep its CLI name in sync if
  plan 029 renames the package.
