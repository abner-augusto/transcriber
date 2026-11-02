# 15 - Engine Smoke Rejects Presets That Name a Hub Model

**Source:** plan 015 smoke tiers, 2026-11-02 (GPU window).

**What happened:** `pytest tests/engine_smoke -m "model_load or model_inference"
--run-engine-smoke --engine-smoke-preset faster-whisper-large-v3` fails both
tiers before loading anything:

```
RuntimeError: Preset model_path must be an existing local path: <repo>\large-v3
```

`scripts/engine_smoke.py::assert_local_preset` requires `model_path` to be a
path on disk, but `model_presets/faster-whisper-large-v3.json` (and the other
faster-whisper Presets) name a model (`"large-v3"`), which faster-whisper
resolves from the Hugging Face cache. The production path loads it fine
offline.

**Evidence that the model itself is fine:** the same `load_preset` and
`infer_preset` functions, run with `HF_HUB_OFFLINE=1` and the guard pointed at
the cached snapshot (`models--Systran--faster-whisper-large-v3`, commit
`edaa852`), passed: load 9.3 s, inference 18.8 s on 12 s of local audio, 25
valid Words. Parakeet passed both tiers through pytest unchanged.

**What to build:** let the local-artifact guard accept a faster-whisper model
name when its weights are already in the local Hugging Face cache (resolve it
offline, for example `faster_whisper.utils.download_model(name,
local_files_only=True)`), and keep rejecting anything that would download.

**Acceptance:**
- The pytest command above passes on this machine with the weights cached and
  no network.
- With the weights absent, the guard still fails before any download.
- A test for both cases with a fake cache.

**Status:** ready-for-agent
