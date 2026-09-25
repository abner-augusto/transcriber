import os
from pathlib import Path
from pydantic_settings import BaseSettings

# Suppress noisy symlink warnings on Windows for huggingface_hub
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


class Settings(BaseSettings):
    database_url: str = "sqlite:///./storage/transcriber.db"
    # Engine binaries. The models they run are named by a Preset, not here — see presets.py.
    whisper_cli_path: str = "../whisper.cpp/build/bin/Release/whisper-cli.exe"
    parakeet_cli_path: str = "../parakeet.cpp/build/examples/cli/Release/parakeet-cli.exe"

    # Dedicated Python interpreters for heavyweight Python Engines.
    qwen3_asr_python: str = "./venv-engines/qwen3-asr/Scripts/python.exe"
    vibevoice_python: str = "./venv-engines/vibevoice/Scripts/python.exe"
    nemotron_diarization_python: str = "./venv-engines/nemotron-diarization/Scripts/python.exe"
    nemotron_diarization_model_path: str = "./models/nemotron-diarization"
    engine_runtime_timeout_seconds: float = 7200.0
    engine_runtime_debug_directory: str = ""

    storage_path: str = "./storage"
    hf_auth_token: str = ""
    cors_origins: str = ""  # Comma-separated, e.g. "http://localhost:3000,http://myapp.com"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8-sig"
        extra = "ignore"  # Be permissive with extra env vars


settings = Settings()

ENGINE_RUNTIME_PYTHON_SETTINGS = {
    "qwen3-asr": "qwen3_asr_python",
    "vibevoice": "vibevoice_python",
    "nemotron-diarization": "nemotron_diarization_python",
}


def engine_runtime_python(engine_id: str) -> str:
    return getattr(settings, ENGINE_RUNTIME_PYTHON_SETTINGS[engine_id])

# Warn about missing critical config at import time
import logging as _logging
_config_log = _logging.getLogger(__name__)
if not settings.hf_auth_token:
    _config_log.warning("HF_AUTH_TOKEN is not set — speaker diarization will not work")


def get_storage_path() -> Path:
    p = Path(settings.storage_path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_meeting_path(meeting_id: str) -> Path:
    p = get_storage_path() / meeting_id
    p.mkdir(parents=True, exist_ok=True)
    return p
