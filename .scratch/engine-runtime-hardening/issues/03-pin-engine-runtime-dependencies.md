# 03 - Pin Reproducible Engine Runtime Dependencies

**Plan:** `plans/003-pin-engine-runtime-dependencies.md`

**What to build:** Replace the implicit editable Qwen/VibeVoice installations and
mixed transitive dependency list with versioned runtime manifests and immutable
direct requirement files. Record and verify each Engine's Python, package,
Transformers, Torch/CUDA, model-type, and optional-capability compatibility.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] Qwen3-ASR and VibeVoice source versions or Git commits are checked into immutable requirement files.
- [ ] Each Engine has a strict, versioned runtime manifest without machine-specific paths.
- [ ] Tested Transformers ranges are recorded independently for each Engine.
- [ ] Clean temporary environments pass `pip check`, required-class imports, and checkpoint metadata validation.
- [ ] Engine code no longer injects a hard-coded external repository into `sys.path`.
- [ ] Installers validate dependencies without silently upgrading them.
- [ ] Tests cover malformed manifests and package/checkpoint incompatibility.

