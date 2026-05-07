import json
from pathlib import Path
from config import settings

_PREFS_FILE = Path("preferences.json")

# Default values for non-sensitive public preferences
_DEFAULTS = {
    "default_vocabulary": "",
    "speaker_profiles_enabled": False,
    "hf_auth_token": "",
    "llm_api_key": "",
}

# Values that should be masked when sending to frontend
_SECRET_KEYS = {"hf_auth_token", "llm_api_key"}


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
        if k in _SECRET_KEYS and v:
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
