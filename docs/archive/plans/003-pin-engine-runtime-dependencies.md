# Plan 003: Pin reproducible Engine runtime dependencies

> **Executor instructions**: Follow the plan without upgrading packages by trial
> and error in the user's active environment. Use temporary environments for
> resolution. Update Plan 003 in `plans/README.md` when done.
>
> **Drift check (run first)**:
> `git diff --stat 5fcd6a8..HEAD -- requirements.txt install.ps1 install.sh README.md INSTALL_WINDOWS.md INSTALL_LINUX.md engines/vibevoice.py`
> Stop if dependency installation has already been reorganized.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: dependencies
- **Planned at**: commit `5fcd6a8`, 2026-09-14

## Why this matters

The repository lists transitive dependencies but omits the actual editable Qwen
and VibeVoice installations and their source commits. It also pins one Transformers
version for models with different compatibility requirements. A reinstall can
therefore produce a runtime that passes `pip check` yet cannot load a configured
checkpoint. Runtime inputs must be versioned and verifiable before process
isolation is introduced in Plan 006.

## Current state

- `requirements.txt:14-43` mixes core, Qwen, and VibeVoice dependencies in one
  uncompiled file and pins `transformers==4.57.6`.
- The inspected environment contains editable installs of Qwen3-ASR commit
  `7c6daf77...` and VibeVoice commit `1541f590...`, but `requirements.txt` contains
  neither direct package reference.
- `engines/vibevoice.py:41-47` injects a machine-specific repository path and
  hard-codes default model paths.
- `install.ps1:157-178` and `install.sh:175-196` install a single environment.
- There is no Python lockfile or checked-in compatibility manifest.
- Qwen's forced-aligner checkpoint declares `model_type=qwen3_asr`; official
  native Transformers support starts at 5.13.0. Do not assume that upgrading the
  shared environment is compatible with the editable Qwen package—prove it.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Dependency integrity | `.\venv\Scripts\python.exe -m pip check` | no broken requirements |
| Manifest tests | `.\venv\Scripts\python.exe -m pytest tests/test_engine_runtime_manifest.py -q` | all pass |
| Backend tests | `.\venv\Scripts\python.exe -m pytest -q` | exit 0 |
| Diff check | `git diff --check` | exit 0 |

## Scope

**In scope**:

- `requirements.txt`
- new files under `requirements/engines/`
- new `engine_runtimes/manifest.py` and manifest data files
- `install.ps1`, `install.sh`
- `README.md`, `INSTALL_WINDOWS.md`, `INSTALL_LINUX.md`
- `tests/test_engine_runtime_manifest.py` (create)

**Out of scope**:

- Switching adapters to subprocesses; Plan 006 owns that.
- Downloading or committing model weights.
- Choosing untested "latest" package versions.
- Changing Whisper, Parakeet, or PyAnnote behavior.

## Git workflow

- Branch: `advisor/003-pin-engine-runtimes`
- Suggested commits:
  `chore(deps): define Engine runtime manifests` and
  `docs(setup): document reproducible Engine environments`.

## Steps

### Step 1: Define a versioned runtime manifest schema

Create a small stdlib-only manifest loader. Each Qwen/VibeVoice manifest must
declare: schema version, Python range, package names and exact versions or Git
commits, supported model types, optional capability requirements, Torch/CUDA
expectation, and a stable runtime ID. Keep paths configurable; manifests must not
contain user-specific absolute paths.

Reject unknown schema fields and malformed version constraints with actionable
errors. Add fixture-based unit tests.

**Verify**: manifest tests pass.

### Step 2: Split direct requirements by runtime

Create `requirements/engines/vibevoice.txt` and
`requirements/engines/qwen3-asr.txt`. Include direct, immutable Git references or
released package pins—not copied transitive dependency lists. Record hashes or
commits and the compatible Transformers range established by a clean-environment
load test. Keep shared application requirements separate.

Resolve each file in a temporary venv. Run `pip check`, import the exact classes,
and parse the configured checkpoint metadata. Record the tested matrix in the
manifest and docs.

**Verify**: both clean temporary environments pass `pip check` and manifest
validation. If they require contradictory Transformers versions, record separate
versions; do not force a common one.

### Step 3: Remove machine-specific import injection

Replace the hard-coded VibeVoice repository `sys.path` modification with a normal
package import and a clear installation error that names the missing runtime.
Keep model paths in Presets/settings, not module constants used as hidden runtime
configuration.

**Verify**: manifest tests and `tests/test_engines.py` pass.

### Step 4: Update installers and documentation

Until Plan 006 switches execution, installers may retain the current core venv,
but they must install immutable direct dependencies and run `pip check` plus a
metadata compatibility check. Document exact repair and verification commands.
Do not silently upgrade existing environments.

**Verify**: PowerShell parser accepts `install.ps1`; `bash -n install.sh` exits 0;
all backend tests pass.

## Test plan

- Valid Qwen and VibeVoice manifests.
- Unknown schema version and missing required fields.
- Package version mismatch.
- Unsupported checkpoint `model_type`.
- Optional aligner dependency mismatch reported separately.
- Manifests contain no absolute user path and all Git dependencies are immutable.

## Done criteria

- [ ] Qwen and VibeVoice direct sources and versions are checked into the repo.
- [ ] Each runtime has a tested Transformers compatibility range.
- [ ] A clean environment can be reconstructed without editable external clones.
- [ ] `pip check` and manifest validation are installer gates.
- [ ] No Engine adapter mutates `sys.path` with a machine-specific path.
- [ ] Documentation matches the actual installer.

## STOP conditions

- A package cannot legally or technically be installed from an immutable source.
- No single environment can satisfy current execution and the proposed change
  would break the working Engine before Plan 006 is ready.
- Validating compatibility requires changing upstream code outside this repo.

## Maintenance notes

Every dependency or checkpoint change must update the runtime manifest and smoke
matrix together. Reviewers should reject floating Git branches and broad untested
version ranges.

