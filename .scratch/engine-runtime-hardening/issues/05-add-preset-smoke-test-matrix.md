# 05 - Add a Tiered Preset Smoke-Test Matrix

**Plan:** `plans/005-add-preset-smoke-test-matrix.md`

**What to build:** Add three Engine verification tiers: deterministic metadata
tests in the normal suite, opt-in local model-load tests, and opt-in tiny-audio
inference tests. Expose the same checks through a human-readable and JSON `doctor`
command.

**Blocked by:** 03 - Pin Reproducible Engine Runtime Dependencies; 04 - Probe Engine Health Before Queueing Jobs.

**Status:** done

- [x] Metadata tests run without model weights, GPU, or network access.
- [x] The original unsupported `qwen3_asr` architecture combination is a regression fixture.
- [x] Model-load and inference tests require explicit opt-in and use local files only.
- [x] Smoke inference checks Word/Turn contracts without asserting hardware-sensitive exact text.
- [x] Every shipped Preset can be selected independently for smoke testing.
- [x] The doctor command returns nonzero for blocked Engines and emits schema-validated JSON.
- [x] Installation and dependency changes document the required smoke commands.

**Verification:** Metadata/doctor tests pass (16 tests). The normal resource-limited
backend suite passes (206 tests, 20 heavy smoke cases deselected). The real JSON
doctor validates its report and returns nonzero for the currently blocked local
Presets. Model-load and inference tiers remain deliberately opt-in and were not run.
