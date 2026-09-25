import json
import re
from pathlib import Path

import pytest

from engine_runtimes.manifest import (
    MANIFEST_DIR,
    ManifestError,
    load_manifest,
    validate_checkpoint,
    validate_environment,
    validate_presets,
)


@pytest.fixture
def valid_manifest_data():
    return json.loads((MANIFEST_DIR / "qwen3-asr.json").read_text(encoding="utf-8"))


def write_manifest(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.mark.parametrize("runtime", ["qwen3-asr", "vibevoice", "nemotron-diarization"])
def test_checked_in_manifests_are_valid_and_portable(runtime):
    manifest = load_manifest(runtime)

    assert manifest.runtime_id.rsplit("-v", 1)[-1].isdigit()
    expected_transformers = {
        "qwen3-asr": "==5.16.1", "vibevoice": "==4.57.6",
        "nemotron-diarization": "==5.18.0.dev0",
    }[runtime]
    assert manifest.transformers == expected_transformers
    raw = (MANIFEST_DIR / f"{runtime}.json").read_text(encoding="utf-8")
    assert "C:/Users/" not in raw
    assert "C:\\Users\\" not in raw


def test_unknown_schema_version_is_rejected(tmp_path, valid_manifest_data):
    valid_manifest_data["schema_version"] = 2

    with pytest.raises(ManifestError, match="Unsupported.*schema_version"):
        load_manifest(write_manifest(tmp_path, valid_manifest_data))


def test_missing_and_unknown_fields_are_rejected(tmp_path, valid_manifest_data):
    del valid_manifest_data["python"]
    valid_manifest_data["mystery"] = True

    with pytest.raises(ManifestError, match="unknown field.*mystery"):
        load_manifest(write_manifest(tmp_path, valid_manifest_data))


def test_malformed_version_constraint_is_actionable(tmp_path, valid_manifest_data):
    valid_manifest_data["transformers"] = "latest"

    with pytest.raises(ManifestError, match="version constraint"):
        load_manifest(write_manifest(tmp_path, valid_manifest_data))


def test_package_version_mismatch_is_reported(monkeypatch):
    manifest = load_manifest("qwen3-asr")

    monkeypatch.setattr("engine_runtimes.manifest.importlib.metadata.version", lambda name: "99.0.0")
    monkeypatch.setattr("engine_runtimes.manifest.importlib.import_module", lambda name: object())

    errors = validate_environment(manifest)
    assert any("transformers 99.0.0 does not satisfy ==5.16.1" in error for error in errors)


def test_unsupported_checkpoint_model_type_is_rejected(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"model_type": "wrong-model"}), encoding="utf-8")

    errors = validate_checkpoint(load_manifest("vibevoice"), tmp_path)

    assert errors == ["checkpoint model_type 'wrong-model' is incompatible; expected one of vibevoice"]


def test_unsupported_vibevoice_aligner_is_reported_separately(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"model_type": "vibevoice"}), encoding="utf-8")

    errors = validate_checkpoint(load_manifest("vibevoice"), tmp_path, capability="forced-alignment")

    assert len(errors) == 1
    assert "optional capability 'forced-alignment' is unsupported" in errors[0]


def test_unsupported_vibevoice_aligner_does_not_require_nonexistent_runtime_classes():
    capability = load_manifest("vibevoice").capabilities["forced-alignment"]

    assert capability["required"] is False
    assert capability["supported"] is False
    assert capability["packages"] == {}
    assert capability["required_imports"] == []


def test_editable_install_cannot_satisfy_immutable_source(monkeypatch):
    manifest = load_manifest("vibevoice")

    class Distribution:
        def read_text(self, name):
            assert name == "direct_url.json"
            return json.dumps({"dir_info": {"editable": True}, "url": "file:///local/clone"})

    monkeypatch.setattr("engine_runtimes.manifest.importlib.metadata.version", lambda name: {
        "vibevoice": "1.0.0", "transformers": "4.57.6", "bitsandbytes": "0.50.0", "torch": "2.11.0",
        "torchaudio": "2.11.0",
    }[name])
    monkeypatch.setattr("engine_runtimes.manifest.importlib.metadata.distribution", lambda name: Distribution())
    monkeypatch.setattr("engine_runtimes.manifest.importlib.import_module", lambda name: object())

    errors = validate_environment(manifest)

    assert any("vibevoice is not installed from immutable commit" in error for error in errors)


def test_preset_checkpoint_validation_uses_configured_paths(tmp_path):
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    (checkpoint / "config.json").write_text(json.dumps({"model_type": "wrong"}), encoding="utf-8")
    presets = tmp_path / "presets"
    presets.mkdir()
    (presets / "qwen.json").write_text(json.dumps({
        "engine": "qwen3-asr", "model_path": str(checkpoint)
    }), encoding="utf-8")

    errors = validate_presets(load_manifest("qwen3-asr"), presets)

    assert errors and "qwen.json" in errors[0] and "wrong" in errors[0]


def test_preset_aligner_validation_uses_configured_path(tmp_path):
    checkpoint = tmp_path / "aligner"
    checkpoint.mkdir()
    (checkpoint / "config.json").write_text(
        json.dumps({"model_type": "qwen3_asr"}), encoding="utf-8"
    )
    presets = tmp_path / "presets"
    presets.mkdir()
    (presets / "vibevoice.json").write_text(
        json.dumps({
            "engine": "vibevoice",
            "model_path": str(tmp_path / "not-downloaded"),
            "aligner_path": str(checkpoint),
        }),
        encoding="utf-8",
    )

    errors = validate_presets(load_manifest("vibevoice"), presets)

    assert len(errors) == 1
    assert "vibevoice.json" in errors[0]
    assert "forced-alignment" in errors[0]


def test_git_requirements_use_full_immutable_commits():
    requirement_dir = Path(__file__).parents[1] / "requirements" / "engines"
    requirement = re.compile(
        r"^[A-Za-z0-9_.-]+ @ git\+https://[^\s@]+@[0-9a-f]{40}$"
    )
    paths = sorted(requirement_dir.glob("*.txt"))

    assert [path.name for path in paths] == ["nemotron-diarization.txt", "qwen3-asr.txt", "vibevoice.txt"]
    for path in paths:
        git_lines = [
            line for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#") and "git+" in line
        ]
        expected_count = 0 if path.name == "qwen3-asr.txt" else 1
        assert len(git_lines) == expected_count
        assert all(requirement.fullmatch(line) for line in git_lines)


def test_installers_install_cuda_torch_inside_each_engine_runtime():
    root = Path(__file__).parents[1]
    for requirements in (root / "requirements" / "engines").glob("*.txt"):
        names = {
            line.split("=", 1)[0].strip().lower()
            for line in requirements.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        assert "torch" not in names
        assert "torchaudio" not in names

    windows = (root / "install.ps1").read_text(encoding="utf-8")
    linux = (root / "install.sh").read_text(encoding="utf-8")
    assert 'uv pip install --reinstall --python $runtimePython torch==2.11.0 torchaudio==2.11.0 --index-url' in windows
    assert 'uv pip install --reinstall --python "$runtime_python" torch==2.11.0 torchaudio==2.11.0 --index-url' in linux
    assert '"nemotron-diarization"' in windows and 'vibevoice nemotron-diarization' in linux
    for installer in (windows, linux):
        assert "nvidia/Nemotron-3-Diarization" in installer
        assert "processor_config.json" in installer
