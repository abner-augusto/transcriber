# Agent Instructions

## Work Tracking

This repository tracks implementation work as local Markdown issues. Read the issue files under `.scratch/*/issues/` before starting planned work. The current speaker-attribution work is under `.scratch/speaker-attribution-precision/issues/`.

Issue status is recorded in each file. A `ready-for-agent` issue is actionable; respect its `Blocked by` field before beginning it. A `needs-exploration` issue has an agreed direction but no agreed interface: run a design session with the user first, write the outcome as a `plans/NNN-*.md`, then flip the issue to `ready-for-agent`. Keep acceptance criteria checkable and update the issue status when the work lands.

`/.scratch` is gitignored so ad-hoc notes stay local. Issue files are tracked on purpose: add new ones with `git add -f`, or they will not exist in the next session's clone.

Executable, step-by-step plans live in `plans/`; `plans/README.md` is the ordered queue with status. The 2026-09-24 architecture review is under `.scratch/architecture-review/` (plans 012 and 013 come from it).

## Domain Context

Read `CONTEXT.md` before changing domain behavior. Consult relevant decisions under `docs/adr/` before changing architecture or engine boundaries.
