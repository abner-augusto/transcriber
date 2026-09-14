# Isolated Engine runtimes

Qwen3-ASR and VibeVoice use separate environments under `venv-engines/`. On
Windows their default interpreters are:

- `venv-engines/qwen3-asr/Scripts/python.exe`
- `venv-engines/vibevoice/Scripts/python.exe`

On Linux and macOS, set `QWEN3_ASR_PYTHON` and `VIBEVOICE_PYTHON` to the respective
`bin/python` paths. Run the metadata doctor from each interpreter after installing
its immutable requirement file. If its fingerprint changes or health reports
`runtime.executable` blocked, rebuild only that Engine environment.

Model-load and inference checks are opt-in because they load large local weights.
Run them sequentially; never keep both GPU Engines resident concurrently.

Runtime crashes, timeouts, malformed responses, and protocol version mismatches
fail the Job. Missing optional forced alignment remains a degraded result using
the proportional timestamp fallback.
