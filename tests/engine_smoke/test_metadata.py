import json

import pytest

from engines.health import probe_engine
from presets import list_presets


def _checkpoint(root, name, model_type):
    path = root / name
    path.mkdir()
    (path / "config.json").write_text(
        json.dumps({"model_type": model_type}), encoding="utf-8"
    )
    (path / "model.safetensors.index.json").write_text(
        json.dumps({"weight_map": {"layer": "model-00001-of-00001.safetensors"}}),
        encoding="utf-8",
    )
    (path / "model-00001-of-00001.safetensors").write_bytes(b"metadata-only")
    return path


def _qwen_runtime(tmp_path, monkeypatch, transformers_version="5.16.1"):
    runtime = tmp_path / "qwen-runtime" / "Scripts" / "python.exe"
    runtime.parent.mkdir(parents=True)
    runtime.touch()
    monkeypatch.setattr("engines.health.settings.qwen3_asr_python", str(runtime))
    versions = {
        "transformers": transformers_version,
        "accelerate": "1.12.0",
        "torch": "2.11.0",
        "torchaudio": "2.11.0",
    }
    monkeypatch.setattr("engines.health._module_source", lambda *_args: __file__)
    monkeypatch.setattr("engines.health._source_defines", lambda *_args: True)
    monkeypatch.setattr("engines.health._cuda_available", lambda: True)

    class Distribution:
        def __init__(self, version): self.version = version
        def read_text(self, _name): return None

    monkeypatch.setattr("engines.health._runtime_distributions", lambda _runtime: {
        name: Distribution(version) for name, version in versions.items()
    })


def test_every_shipped_preset_is_independently_selectable():
    presets = list_presets()
    ids = [preset["id"] for preset in presets]
    assert ids
    assert len(ids) == len(set(ids))
    assert all(preset.get("engine") and preset.get("model_path") for preset in presets)


def test_qwen3_asr_primary_checkpoint_is_blocked_on_unsupported_runtime(
    tmp_path, monkeypatch
):
    _qwen_runtime(tmp_path, monkeypatch, transformers_version="5.15.1")
    primary = _checkpoint(tmp_path, "primary", "qwen3_asr")
    health = probe_engine(
        {"engine": "qwen3-asr", "model_path": str(primary), "device": "cuda"}
    )
    assert health.state == "blocked"
    assert any(
        check.code == "runtime.package.transformers"
        and check.required
        and not check.passed
        for check in health.checks
    )


def test_qwen3_asr_optional_aligner_is_supported(tmp_path, monkeypatch):
    _qwen_runtime(tmp_path, monkeypatch)
    primary = _checkpoint(tmp_path, "primary", "qwen3_asr")
    aligner = _checkpoint(tmp_path, "aligner", "qwen3_asr")
    health = probe_engine(
        {
            "engine": "qwen3-asr",
            "model_path": str(primary),
            "aligner_path": str(aligner),
            "device": "cuda",
        }
    )
    assert health.state == "ready"
    assert any(
        check.code == "capability.forced-alignment.model_type"
        and not check.required
        and check.passed
        for check in health.checks
    )


@pytest.mark.parametrize("preset", list_presets(), ids=lambda preset: preset["id"])
def test_metadata_probe_has_stable_contract(preset):
    health = probe_engine(preset).to_dict()
    assert health["state"] in {"ready", "degraded", "blocked"}
    assert health["fingerprint"]
    assert isinstance(health["checks"], (list, tuple))
    assert all(
        set(check) == {"code", "required", "passed", "message"}
        for check in health["checks"]
    )
