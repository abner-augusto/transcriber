# 04 - Probe Engine Health Before Queueing Jobs

**Plan:** `plans/004-probe-engine-health-before-queueing.md`

**What to build:** Introduce structured, fast Engine health probes with `ready`,
`degraded`, and `blocked` states. Validate package/class, checkpoint metadata,
shards, optional aligner, device, and CUDA compatibility without loading weights.
Enforce blocked health at every API boundary that can queue a Job.

**Blocked by:** 03 - Pin Reproducible Engine Runtime Dependencies.

**Status:** done

- [x] Every Preset has structured health with stable check codes and a runtime fingerprint.
- [x] Required failures are `blocked`; optional failures are `degraded`.
- [x] Fast probes do not load weights, allocate GPU memory, use the network, or mutate the environment.
- [x] Blocked Presets cannot be made default, duplicated for processing, or queued through direct API calls.
- [x] Degraded Presets remain selectable with a visible warning.
- [x] Frontend selectors never auto-select a blocked Preset.
- [x] Backend and frontend tests cover all states and queue enforcement.

**Verification:** Health/API tests pass (11 tests), frontend tests pass (25 tests),
the production frontend build succeeds, and the resource-limited backend suite
passes (190 tests). Validation ran sequentially with GPU disabled.
