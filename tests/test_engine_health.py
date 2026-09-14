import json

from engines.health import probe_engine


def _checkpoint(tmp_path, model_type="vibevoice", missing_shard=False):
    path = tmp_path / model_type
    path.mkdir()
    (path / "config.json").write_text(json.dumps({"model_type": model_type}), encoding="utf-8")
    (path / "model.safetensors.index.json").write_text(
        json.dumps({"weight_map": {"layer": "model-00001-of-00001.safetensors"}}),
        encoding="utf-8",
    )
    if not missing_shard:
        (path / "model-00001-of-00001.safetensors").write_bytes(b"fixture")
    return path


def _compatible_runtime(monkeypatch):
    versions = {"vibevoice": "1.0.0", "transformers": "4.57.6", "torch": "2.11.0", "torchaudio": "2.11.0"}
    monkeypatch.setattr("engines.health._distribution_version", versions.get)
    monkeypatch.setattr("engines.health._module_source", lambda _distribution, _module: __file__)
    monkeypatch.setattr("engines.health._source_defines", lambda _path, _attribute: True)
    monkeypatch.setattr("engines.health._cuda_available", lambda: True)

    class Distribution:
        def read_text(self, _name):
            # Both checked-in manifests use one immutable source commit. The probe
            # reads this through metadata rather than importing either Engine.
            return json.dumps({"vcs_info": {"commit_id": "1541f590c7099820f10ea012f48d2399282df69f"}})

    monkeypatch.setattr("engines.health.importlib.metadata.distribution", lambda _name: Distribution())


def test_fast_probe_reports_ready_without_importing_engine(tmp_path, monkeypatch):
    _compatible_runtime(monkeypatch)
    health = probe_engine({"engine": "vibevoice", "model_path": str(_checkpoint(tmp_path)), "device": "cuda"})
    assert health.state == "ready"
    assert health.fingerprint
    assert all(check.passed for check in health.checks)


def test_missing_required_shard_blocks_preset(tmp_path, monkeypatch):
    _compatible_runtime(monkeypatch)
    health = probe_engine({"engine": "vibevoice", "model_path": str(_checkpoint(tmp_path, missing_shard=True)), "device": "cuda"})
    assert health.state == "blocked"
    assert any(check.code == "checkpoint.primary.shards" and not check.passed for check in health.checks)
    assert health.to_dict()["available"] is False


def test_optional_aligner_incompatibility_is_degraded(tmp_path, monkeypatch):
    _compatible_runtime(monkeypatch)
    health = probe_engine({
        "engine": "vibevoice",
        "model_path": str(_checkpoint(tmp_path)),
        "aligner_path": str(tmp_path / "aligner"),
        "device": "cuda",
    })
    assert health.state == "degraded"
    assert any(check.code == "capability.forced-alignment.runtime" and not check.required for check in health.checks)


def test_cuda_request_without_driver_blocks_preset(tmp_path, monkeypatch):
    _compatible_runtime(monkeypatch)
    monkeypatch.setattr("engines.health._cuda_available", lambda: False)
    health = probe_engine({"engine": "vibevoice", "model_path": str(_checkpoint(tmp_path)), "device": "cuda"})
    assert health.state == "blocked"
    assert any(check.code == "device.cuda" and not check.passed for check in health.checks)
