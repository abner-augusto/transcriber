"""Explicit, local-only Engine load and inference smoke operations."""

from __future__ import annotations

import gc
import math
import os
import subprocess
from pathlib import Path


def _local_artifact(value: str, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.exists():
        raise RuntimeError(f"{label} must be an existing local path: {path}")
    return path


def assert_local_preset(preset: dict) -> None:
    _local_artifact(preset.get("model_path", ""), "Preset model_path")
    if preset.get("aligner_path"):
        _local_artifact(preset["aligner_path"], "Preset aligner_path")


def load_preset(preset: dict) -> dict:
    """Load a selected Preset without permitting remote model resolution."""
    assert_local_preset(preset)
    # Belt-and-suspenders protection for libraries that otherwise resolve model
    # identifiers remotely. Preset paths were already proven local above.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    from engines import make_transcriber

    transcriber = make_transcriber(preset)
    engine = preset["engine"]
    if engine == "qwen3-asr":
        transcriber._ensure_asr_loaded()
        transcriber._ensure_aligner_loaded()
    elif engine == "vibevoice":
        transcriber._ensure_model_loaded()
        transcriber._ensure_aligner_loaded()
    elif engine == "faster-whisper":
        transcriber.get_model(
            transcriber.model_path, transcriber.device, transcriber.compute_type
        )
    # Native executable Engines are fully checked by metadata health. Their model
    # files are opened by inference because they expose no separate load command.
    return {"status": "passed", "engine": engine, "preset_id": preset["id"]}


def validate_words(words, duration: float) -> None:
    if not words:
        raise RuntimeError("Engine returned no Words")
    previous_start = 0.0
    for word in words:
        if not all(math.isfinite(value) for value in (word.start, word.end)):
            raise RuntimeError("Word timestamps must be finite")
        if word.start < 0 or word.end < word.start or word.end > duration + 1.0:
            raise RuntimeError("Word timestamps are outside the local audio bounds")
        if word.start < previous_start:
            raise RuntimeError("Words must be ordered")
        if not word.text or not word.text.strip():
            raise RuntimeError("Words must contain join-ready text")
        previous_start = word.start
    if not "".join(word.text for word in words).strip():
        raise RuntimeError("joined Word text must be nonempty")


def validate_turns(turns, duration: float) -> None:
    previous_start = 0.0
    for turn in turns:
        if not all(math.isfinite(value) for value in (turn.start, turn.end)):
            raise RuntimeError("Turn timestamps must be finite")
        if turn.start < 0 or turn.end < turn.start or turn.end > duration + 1.0:
            raise RuntimeError("Turn timestamps are outside the local audio bounds")
        if turn.start < previous_start or not turn.speaker:
            raise RuntimeError("Turns must be ordered and identify a Speaker")
        previous_start = turn.start


def infer_preset(preset: dict, audio_path: Path) -> dict:
    """Run one selected Preset against an existing local audio file."""
    assert_local_preset(preset)
    audio_path = _local_artifact(str(audio_path), "Engine smoke audio")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    from engines import make_transcriber

    transcriber = make_transcriber(preset)
    words = transcriber.transcribe(str(audio_path), vocabulary=None)
    duration_result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "csv=p=0", str(audio_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    duration = float(duration_result.stdout.strip())
    validate_words(words, duration)
    turns = []
    if getattr(transcriber, "has_native_diarization", False):
        turns = list(transcriber.get_native_diarization().turns)
        validate_turns(turns, duration)
    return {
        "status": "passed",
        "engine": preset["engine"],
        "preset_id": preset["id"],
        "word_count": len(words),
        "turn_count": len(turns),
    }


def release_engine_memory() -> None:
    """Best-effort cleanup, imported only inside an opted-in smoke process."""
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass
