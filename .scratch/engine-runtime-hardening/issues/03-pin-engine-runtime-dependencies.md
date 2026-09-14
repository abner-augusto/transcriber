# 03 - Pin Reproducible Engine Runtime Dependencies

**Plan:** `plans/003-pin-engine-runtime-dependencies.md`

**What to build:** Replace the implicit editable Qwen/VibeVoice installations and
mixed transitive dependency list with versioned runtime manifests and immutable
direct requirement files. Record and verify each Engine's Python, package,
Transformers, Torch/CUDA, model-type, and optional-capability compatibility.

**Blocked by:** None — can start immediately.

**Status:** done

- [x] Qwen3-ASR and VibeVoice source versions or Git commits are checked into immutable requirement files.
- [x] Each Engine has a strict, versioned runtime manifest without machine-specific paths.
- [x] Tested Transformers ranges are recorded independently for each Engine.
- [x] Clean temporary environments pass `pip check`, required-class imports, and checkpoint metadata validation.
- [x] Engine code no longer injects a hard-coded external repository into `sys.path`.
- [x] Installers validate dependencies without silently upgrading them.
- [x] Tests cover malformed manifests and package/checkpoint incompatibility.

**Verification:** Isolated Qwen and VibeVoice environments pass dependency,
immutable-source, required-import, and configured checkpoint metadata validation.
Manifest tests pass (14 tests), the backend suite passes (183 tests), and both
installer scripts pass syntax validation. All validation ran sequentially with GPU
disabled and CPU thread counts limited.
