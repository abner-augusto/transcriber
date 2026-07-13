"""Presets: the named model configurations a Meeting can be transcribed with.

A Preset is one JSON file in model_presets/. It names an Engine and the model to run
on it, plus whatever that Engine needs to know:

    {"id": "parakeet-tdt-0.6b-v3", "name": "Parakeet TDT 0.6B v3",
     "engine": "parakeet.cpp", "model_path": "./models/parakeet/tdt-0.6b-v3-q4_k.gguf",
     "decoder": "tdt"}

There is one default, and a Meeting may override it — that is what makes an A/B run
on real audio possible. Files are read on every call: there are a handful of them,
they are tiny, and a cache here would only be a way to serve a stale one.
"""

import json
import logging
import re
from pathlib import Path

from config import get_storage_path

log = logging.getLogger(__name__)

PRESETS_DIR = Path(__file__).parent / "model_presets"
FALLBACK_PRESET_ID = "whisper-large-v3-turbo"


def list_presets() -> list[dict]:
    """Every Preset on disk, by name."""
    presets = []
    for path in sorted(PRESETS_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning(f"Ignoring unreadable preset {path.name}: {e}")
            continue
        data.setdefault("id", path.stem)
        presets.append(data)
    return sorted(presets, key=lambda p: p.get("name", p["id"]))


def get_preset(preset_id: str) -> dict | None:
    return next((p for p in list_presets() if p["id"] == preset_id), None)


def resolve_preset(preset_id: str | None = None) -> dict:
    """The Preset to actually transcribe with.

    Prefers the Meeting's override, falls back to the default, and finally to any
    Preset at all — so a bad id in the database cannot leave a Job with no Engine.
    """
    presets = list_presets()
    if not presets:
        raise RuntimeError(f"No presets found in {PRESETS_DIR}")

    by_id = {p["id"]: p for p in presets}
    for candidate in (preset_id, default_preset_id(), FALLBACK_PRESET_ID):
        if candidate and candidate in by_id:
            return by_id[candidate]

    log.warning(f"Preset '{preset_id}' not found; falling back to '{presets[0]['id']}'")
    return presets[0]


def default_preset_id() -> str:
    return _load_settings().get("default_preset", FALLBACK_PRESET_ID)


def set_default_preset(preset_id: str) -> None:
    if not get_preset(preset_id):
        raise ValueError(f"Preset not found: {preset_id}")
    settings = _load_settings()
    settings["default_preset"] = preset_id
    _save_settings(settings)


def create_preset(data: dict) -> dict:
    """Write a new Preset. The id is derived from the name, so names are unique."""
    preset_id = re.sub(r"[^a-z0-9-]", "-", data["name"].lower()).strip("-")
    if not preset_id:
        raise ValueError("Preset name must contain at least one letter or digit")

    preset = {**data, "id": preset_id}
    PRESETS_DIR.mkdir(parents=True, exist_ok=True)
    (PRESETS_DIR / f"{preset_id}.json").write_text(
        json.dumps(preset, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return preset


def delete_preset(preset_id: str) -> None:
    path = PRESETS_DIR / f"{preset_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Preset not found: {preset_id}")
    path.unlink()

    settings = _load_settings()
    if settings.get("default_preset") == preset_id:
        del settings["default_preset"]
        _save_settings(settings)


def _settings_path() -> Path:
    return get_storage_path() / "settings.json"


def _load_settings() -> dict:
    path = _settings_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning(f"Unreadable settings.json, using defaults: {e}")
        return {}


def _save_settings(settings: dict) -> None:
    _settings_path().write_text(json.dumps(settings, indent=2), encoding="utf-8")
