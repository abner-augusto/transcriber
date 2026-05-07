from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://transcriber:transcriber@localhost:5433/transcriber"
    redis_url: str = "redis://localhost:6380/0"
    
    # LLM Settings (OpenAI-compatible API)
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_api_key: str = ""
    llm_model: str = "anthropic/claude-3.5-sonnet"
    
    whisper_cli_path: str = "../whisper.cpp/build/bin/Release/whisper-cli.exe"
    whisper_model_path: str = "./models/ggml-large-v3-turbo.bin"
    whisper_small_model_path: str = "./models/ggml-small.bin"
    storage_path: str = "./storage"
    hf_auth_token: str = ""
    cors_origins: str = ""  # Comma-separated, e.g. "http://localhost:3000,http://myapp.com"

    # Live mode settings
    live_chunk_overlap_seconds: float = 2.5
    live_speaker_threshold: float = 0.45
    live_min_segment_duration: float = 2.0

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
if not settings.llm_api_key and "openrouter" in settings.llm_base_url:
    _config_log.warning("LLM_API_KEY is not set — LLM features will fail for this provider")


def get_storage_path() -> Path:
    p = Path(settings.storage_path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_meeting_path(meeting_id: str) -> Path:
    p = get_storage_path() / meeting_id
    p.mkdir(parents=True, exist_ok=True)
    return p
