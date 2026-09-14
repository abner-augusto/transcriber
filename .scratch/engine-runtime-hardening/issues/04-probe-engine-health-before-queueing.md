# 04 - Probe Engine Health Before Queueing Jobs

**Plan:** `plans/004-probe-engine-health-before-queueing.md`

**What to build:** Introduce structured, fast Engine health probes with `ready`,
`degraded`, and `blocked` states. Validate package/class, checkpoint metadata,
shards, optional aligner, device, and CUDA compatibility without loading weights.
Enforce blocked health at every API boundary that can queue a Job.

**Blocked by:** 03 - Pin Reproducible Engine Runtime Dependencies.

**Status:** blocked

- [ ] Every Preset has structured health with stable check codes and a runtime fingerprint.
- [ ] Required failures are `blocked`; optional failures are `degraded`.
- [ ] Fast probes do not load weights, allocate GPU memory, use the network, or mutate the environment.
- [ ] Blocked Presets cannot be made default, duplicated for processing, or queued through direct API calls.
- [ ] Degraded Presets remain selectable with a visible warning.
- [ ] Frontend selectors never auto-select a blocked Preset.
- [ ] Backend and frontend tests cover all states and queue enforcement.

