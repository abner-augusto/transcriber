# Agent Instructions

## Work Tracking

Implementation work is tracked as local Markdown issues under `.scratch/*/issues/`; read the relevant ones before starting planned work.

Issue status is recorded in each file. A `ready-for-agent` issue is actionable; respect its `Blocked by` field before beginning it. A `needs-exploration` issue has an agreed direction but no agreed interface: run a design session with the user first, write the outcome as a `plans/NNN-*.md`, then flip the issue to `ready-for-agent`. Keep acceptance criteria checkable and update the issue status when the work lands.

`/.scratch` is gitignored so ad-hoc notes stay local, but issue files are tracked on purpose: add new ones with `git add -f`, or they will not exist in the next session's clone.

Executable, step-by-step plans live in `plans/`; `plans/README.md` is the ordered queue with status.

## Domain Context

Read `GLOSSARY.md` before changing domain behavior. Consult relevant decisions under `docs/adr/` before changing architecture or engine boundaries.

## Operating the app

To transcribe, name Speakers, or correct a Meeting (rather than change the code),
follow `.claude/skills/transcriber-operator/SKILL.md`; it drives the running app
through `uv run python -m transcriber_cli`. ADR-0010 says why that is allowed.

## Every change

1. **Docs**: update the docs the change touches, so none contradicts the code or another doc.
2. **Tests**: call the `tdd` skill; the new test goes red before the implementation.
3. **Implementation**: only what turns the test green, with every caller of a replaced path updated in the same change.
4. **Cleanup**: delete the code, files and docs the change made unused (git history is the backup). Unsure → ask. `plans/` and `docs/adr/` are records, not cleanup targets.

Ask before any destructive data operation (database, `storage/`, `models/`).

## Done

The gate output is read: `pytest` from the repo root (fake Engines, no GPU; the `model_*` markers are opt-in) and `npm test` in `frontend/`. The report lists what you deleted.

## Corrections

Read `docs/lessons.md` before changing code. When the user corrects you, add a "When X, do Y" line at its top. A mechanical mistake becomes a check (test, lint rule, gate), not a lesson. The same mistake twice means the lesson is unclear: rewrite it. Past 20 lessons, merge duplicates, drop outdated ones, and show the result.
