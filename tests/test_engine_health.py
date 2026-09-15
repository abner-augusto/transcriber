import json

from engines.health import _source_defines, probe_engine


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


def test_required_class_scanner_accepts_explicit_reexport(tmp_path):
    module = tmp_path / "__init__.py"
    module.write_text(
        "from .modeling import RuntimeModel as ExportedModel\n",
        encoding="utf-8",
    )

    assert _source_defines(module, "ExportedModel") is True


def _compatible_runtime(tmp_path, monkeypatch):
    runtime = tmp_path / "vibevoice-runtime" / "Scripts" / "python.exe"
    runtime.parent.mkdir(parents=True)
    runtime.touch()
    monkeypatch.setattr("engines.health.settings.vibevoice_python", str(runtime))
    versions = {"vibevoice": "1.0.0", "transformers": "4.57.6", "bitsandbytes": "0.50.0", "torch": "2.11.0", "torchaudio": "2.11.0"}
    monkeypatch.setattr("engines.health._module_source", lambda *_args: __file__)
    monkeypatch.setattr("engines.health._source_defines", lambda _path, _attribute: True)
    monkeypatch.setattr("engines.health._cuda_available", lambda: True)

    class Distribution:
        def __init__(self, version): self.version = version
        def read_text(self, _name):
            # Both checked-in manifests use one immutable source commit. The probe
            # reads this through metadata rather than importing either Engine.
            return json.dumps({"vcs_info": {"commit_id": "1541f590c7099820f10ea012f48d2399282df69f"}})

    monkeypatch.setattr("engines.health._runtime_distributions", lambda _runtime: {name: Distribution(version) for name, version in versions.items()})


def test_runtime_probe_ignores_packages_visible_only_to_core(tmp_path, monkeypatch):
    runtime = tmp_path / "empty-runtime" / "Scripts" / "python.exe"
    runtime.parent.mkdir(parents=True); runtime.touch()
    (runtime.parent.parent / "Lib" / "site-packages").mkdir(parents=True)
    monkeypatch.setattr("engines.health.settings.vibevoice_python", str(runtime))
    monkeypatch.setattr("engines.health.importlib.metadata.version", lambda _name: "999.0")
    monkeypatch.setattr("engines.health._cuda_available", lambda: True)
    health = probe_engine({"engine": "vibevoice", "model_path": str(_checkpoint(tmp_path)), "device": "cuda"})
    assert health.state == "blocked"
    assert any(check.code == "runtime.package.vibevoice" and not check.passed for check in health.checks)


def test_runtime_distribution_metadata_comes_from_selected_site_packages(tmp_path):
    runtime = tmp_path / "selected-runtime" / "Scripts" / "python.exe"
    runtime.parent.mkdir(parents=True); runtime.touch()
    site = runtime.parent.parent / "Lib" / "site-packages"; site.mkdir(parents=True)
    info = site / "example_engine-1.2.3.dist-info"; info.mkdir()
    (info / "METADATA").write_text("Metadata-Version: 2.1\nName: example-engine\nVersion: 1.2.3\n", encoding="utf-8")
    module = site / "example_engine"; module.mkdir()
    (module / "__init__.py").write_text("class RuntimeClass:\n    pass\n", encoding="utf-8")
    (info / "RECORD").write_text("example_engine/__init__.py,,\nexample_engine-1.2.3.dist-info/METADATA,,\n", encoding="utf-8")
    from engines.health import _distribution_version, _module_source, _runtime_distributions, _source_defines
    distributions = _runtime_distributions(runtime)
    assert _distribution_version("example-engine", distributions) == "1.2.3"
    source = _module_source("example-engine", "example_engine", distributions)
    assert source == module / "__init__.py"
    assert _source_defines(source, "RuntimeClass")


def test_fast_probe_reports_ready_without_importing_engine(tmp_path, monkeypatch):
    _compatible_runtime(tmp_path, monkeypatch)
    health = probe_engine({"engine": "vibevoice", "model_path": str(_checkpoint(tmp_path)), "device": "cuda"})
    assert health.state == "ready"
    assert health.fingerprint
    assert all(check.passed for check in health.checks)


def test_missing_required_shard_blocks_preset(tmp_path, monkeypatch):
    _compatible_runtime(tmp_path, monkeypatch)
    health = probe_engine({"engine": "vibevoice", "model_path": str(_checkpoint(tmp_path, missing_shard=True)), "device": "cuda"})
    assert health.state == "blocked"
    assert any(check.code == "checkpoint.primary.shards" and not check.passed for check in health.checks)
    assert health.to_dict()["available"] is False


def test_optional_aligner_incompatibility_is_degraded(tmp_path, monkeypatch):
    _compatible_runtime(tmp_path, monkeypatch)
    health = probe_engine({
        "engine": "vibevoice",
        "model_path": str(_checkpoint(tmp_path)),
        "aligner_path": str(tmp_path / "aligner"),
        "device": "cuda",
    })
    assert health.state == "degraded"
    assert any(check.code == "capability.forced-alignment.runtime" and not check.required for check in health.checks)


def test_cuda_request_without_driver_blocks_preset(tmp_path, monkeypatch):
    _compatible_runtime(tmp_path, monkeypatch)
    monkeypatch.setattr("engines.health._cuda_available", lambda: False)
    health = probe_engine({"engine": "vibevoice", "model_path": str(_checkpoint(tmp_path)), "device": "cuda"})
    assert health.state == "blocked"
    assert any(check.code == "device.cuda" and not check.passed for check in health.checks)
