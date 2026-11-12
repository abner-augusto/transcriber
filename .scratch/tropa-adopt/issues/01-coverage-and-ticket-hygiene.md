# 01 - Measure CRAP in the check and tidy the ticket files

**Status:** done

**Source:** tropa adoption, 2026-11-12. Decisions made by the owner.

## What to build

1. **Python coverage in the check.** Add `pytest-cov` to the `dev` extra in `pyproject.toml` (update `uv.lock`). Make `scripts/check` run pytest with coverage and write `coverage.json` at the repo root (`--cov --cov-report=json:coverage.json`, limited to the repo's own packages). Add `coverage.json` and `.coverage` to `.gitignore`. Keep the check offline for every other step. The frontend keeps running without coverage: `[quality] coverage` holds one path.
2. **Baseline with CRAP.** Before touching the baseline, run `tropa quality .` and confirm it says `0 new | 0 grown`. Then run the check once so `coverage.json` exists, and run `tropa quality --init-baseline .` so today's `function.crap` findings enter `docs/agents/quality-baseline.json`. Compare the baseline before and after: every entry that existed before must still be there with the same value; only `function.crap` entries may be added.
3. **Ticket hygiene** under `.scratch/`:
   - Track `.scratch/asr-engine-gpu-fixes/issues/01-*.md` with `git add -f`.
   - One status vocabulary, the one `AGENTS.md` and the tropa lanes use: `needs-triage`, `needs-exploration`, `ready-for-agent`, `ready-for-human`, `claimed`, `in-progress`, `done`. Rewrite only the status word at the start of each `**Status:**` line (`completed`, `DONE`, `closed-fixed` become `done`); keep whatever explanation follows it on the line.
   - `.scratch/architecture-review/issues/05-stack-simplification.md`: its only open criterion is a clean Linux install, which needs a person and a Linux machine. Set its status to `ready-for-human`, keeping the explanation.

## Acceptance criteria

- [ ] `bash scripts/check` exits 0 and its output shows pytest ran with coverage; `coverage.json` exists and is git-ignored.
- [ ] `tropa quality .` prints `0 new | 0 grown` and no longer prints `crap: not run`.
- [ ] The baseline diff adds only `function.crap` entries; no earlier entry changed or disappeared.
- [ ] `rg -n '^\*\*Status:\*\* (completed|DONE|closed-fixed)' .scratch` finds nothing.
- [ ] `git ls-files .scratch/asr-engine-gpu-fixes` lists the ticket.
- [ ] Ticket 05 starts with `**Status:** ready-for-human`.

## Out of scope

- No GPU or `model_*` test, no model download, nothing that touches `storage/`, `models/` or the database.
- No change to application code or tests.
- No push: commit on `main` and report; the orchestrator pushes.

## Commits

Three commits in the repo's convention (English, sentence subject, no trailers): coverage in the check, the baseline, the ticket hygiene. This ticket file is added with `git add -f` and its status set to `done` in the last commit.
