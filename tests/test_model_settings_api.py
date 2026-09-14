import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from main import app
import presets

client = TestClient(app)


class FakeHealth:
    def __init__(self, state="ready"):
        self.state = state

    def to_dict(self):
        return {
            "state": self.state,
            "summary": "Engine is ready" if self.state == "ready" else "runtime mismatch",
            "checks": [],
            "fingerprint": "fixture",
            "available": self.state != "blocked",
            "reason": None if self.state == "ready" else "runtime mismatch",
        }


def test_update_preset_modifies_parameters_in_place(tmp_path, monkeypatch):
    monkeypatch.setattr(presets, "PRESETS_DIR", tmp_path)
    monkeypatch.setattr("api.model_settings.probe_engine", lambda _preset: FakeHealth())

    # Create dummy preset
    preset_data = {
        "id": "test-preset",
        "name": "Test Preset",
        "engine": "qwen3-asr",
        "model_path": "./models/test.bin",
        "device": "cpu",
    }
    (tmp_path / "test-preset.json").write_text(json.dumps(preset_data), encoding="utf-8")

    # Update via API
    resp = client.put(
        "/api/model-settings/presets/test-preset",
        json={
            "model_path": "./models/updated.bin",
            "device": "cuda",
            "aligner_path": "./models/aligner.bin",
        },
    )
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["id"] == "test-preset"
    assert updated["model_path"] == "./models/updated.bin"
    assert updated["device"] == "cuda"
    assert updated["aligner_path"] == "./models/aligner.bin"

    # Verify on disk
    on_disk = json.loads((tmp_path / "test-preset.json").read_text(encoding="utf-8"))
    assert on_disk["model_path"] == "./models/updated.bin"
    assert on_disk["device"] == "cuda"
    assert on_disk["aligner_path"] == "./models/aligner.bin"


def test_update_nonexistent_preset_returns_404(tmp_path, monkeypatch):
    monkeypatch.setattr(presets, "PRESETS_DIR", tmp_path)

    resp = client.put(
        "/api/model-settings/presets/nonexistent-id",
        json={"model_path": "./models/any.bin"},
    )
    assert resp.status_code == 404


def test_blocked_preset_cannot_be_made_default(tmp_path, monkeypatch):
    monkeypatch.setattr(presets, "PRESETS_DIR", tmp_path)
    (tmp_path / "blocked.json").write_text(json.dumps({
        "id": "blocked", "name": "Blocked", "engine": "vibevoice", "model_path": "missing"
    }), encoding="utf-8")
    monkeypatch.setattr("api.model_settings.probe_engine", lambda _preset: FakeHealth("blocked"))

    response = client.put("/api/model-settings", json={"default_preset": "blocked"})

    assert response.status_code == 409
    assert response.json()["detail"]["health"]["state"] == "blocked"


def test_blocked_update_does_not_mutate_preset(tmp_path, monkeypatch):
    monkeypatch.setattr(presets, "PRESETS_DIR", tmp_path)
    original = {"id": "test", "name": "Test", "engine": "vibevoice", "model_path": "working"}
    path = tmp_path / "test.json"
    path.write_text(json.dumps(original), encoding="utf-8")
    monkeypatch.setattr("api.model_settings.probe_engine", lambda _preset: FakeHealth("blocked"))

    response = client.put("/api/model-settings/presets/test", json={"model_path": "broken"})

    assert response.status_code == 409
    assert json.loads(path.read_text(encoding="utf-8")) == original
