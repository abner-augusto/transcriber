import os
from pathlib import Path
from pydantic_settings import BaseSettings

# Suppress noisy symlink warnings on Windows for huggingface_hub
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


class Settings(BaseSettings):
    database_url: str = "postgresql://transcriber:transcriber@localhost:5433/transcriber"
    redis_url: str = "redis://localhost:6380/0"

    # Engine binaries. The models they run are named by a Preset, not here — see presets.py.
    whisper_cli_path: str = "../whisper.cpp/build/bin/Release/whisper-cli.exe"
    parakeet_cli_path: str = "../parakeet.cpp/build/examples/cli/Release/parakeet-cli.exe"

    storage_path: str = "./storage"
    hf_auth_token: str = ""
    cors_origins: str = ""  # Comma-separated, e.g. "http://localhost:3000,http://myapp.com"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8-sig"
        extra = "ignore"  # Be permissive with extra env vars


settings = Settings()

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
