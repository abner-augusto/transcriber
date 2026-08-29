import json
import math
from pathlib import Path
from config import settings

_PREFS_FILE = Path("preferences.json")
DEFAULT_SPEAKER_SWITCH_PENALTY = 0.8
MIN_SPEAKER_SWITCH_PENALTY = 0.0
MAX_SPEAKER_SWITCH_PENALTY = 2.0

# Default values for non-sensitive public preferences
_DEFAULTS = {
    "default_vocabulary": "",
    "speaker_profiles_enabled": False,
    "hf_auth_token": "",
    "speaker_switch_penalty": DEFAULT_SPEAKER_SWITCH_PENALTY,
    # Forced alignment settings. Disabled by default so standard path is untouched.
    # Keys: "enabled" (bool), "model" (str, default "mms-fa"), "device" (str, default "auto").
    "forced_alignment": {
        "enabled": False,
        "model": "mms-fa",
        "device": "auto",
    },
    # Whisper DTW timestamp settings.
    # Keys: "enabled" (bool, default True), "preset" (str, default "" for auto).
    "whisper_dtw": {
        "enabled": True,
        "preset": "",
    },
    # Diarization clustering overrides. Empty => pyannote's own calibrated defaults.
    # Recognised keys: "clustering_threshold" (0-1), "Fa", "Fb".
    "diarization": {},
}

# Values that should be masked when sending to frontend
_SECRET_KEYS = {"hf_auth_token"}


def load_preferences() -> dict:
    if not _PREFS_FILE.exists():
        return _DEFAULTS.copy()
    try:
        with open(_PREFS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Merge defaults to handle new keys
            return {**_DEFAULTS, **data}
    except Exception:
        return _DEFAULTS.copy()


def save_preferences(prefs: dict):
    with open(_PREFS_FILE, "w", encoding="utf-8") as f:
        json.dump(prefs, f, indent=2, ensure_ascii=False)


def get_public_preferences() -> dict:
    """Return preferences with secrets masked for the frontend."""
    prefs = load_preferences()
    public = {}
    for k, v in prefs.items():
        if k == "speaker_switch_penalty":
            public[k] = _coerce_speaker_switch_penalty(v)
        elif k in _SECRET_KEYS and v:
            # Mask secret
            public[k] = v[:3] + "*" * 10 + v[-3:] if len(v) > 6 else "*" * 10
        else:
            public[k] = v
    return public


def get_secret(key: str) -> str:
    """Get secret from preferences or fall back to env/settings."""
    prefs = load_preferences()
    if prefs.get(key):
        return prefs[key]

    # Fallback to settings (which reads from env)
    return getattr(settings, key, "")


def get_speaker_switch_penalty() -> float:
    """Return a finite, bounded continuity penalty from persisted preferences."""
    value = load_preferences().get("speaker_switch_penalty", DEFAULT_SPEAKER_SWITCH_PENALTY)
    return _coerce_speaker_switch_penalty(value)


def _coerce_speaker_switch_penalty(value) -> float:
    try:
        penalty = float(value)
    except (TypeError, ValueError):
        return DEFAULT_SPEAKER_SWITCH_PENALTY
    if not math.isfinite(penalty) or not MIN_SPEAKER_SWITCH_PENALTY <= penalty <= MAX_SPEAKER_SWITCH_PENALTY:
        return DEFAULT_SPEAKER_SWITCH_PENALTY
    return penalty
