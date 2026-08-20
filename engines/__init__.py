"""Engines: the interchangeable half of the pipeline.

A Preset names an Engine ("whisper.cpp") and the model to run on it. This registry
turns that name into an adapter. Adding an Engine is therefore two files — an adapter
here and a Preset JSON in model_presets/ — and nothing in tasks/ changes.

Imports of the adapters are deferred: the API process lists Presets without paying
for torch, and a machine with no parakeet build can still run whisper.
"""

from pathlib import Path

from config import settings

from .ports import Diarizer, Transcriber, Turn, Word

__all__ = [
    "Word", "Turn", "Transcriber", "Diarizer",
    "make_transcriber", "make_diarizer",
    "TRANSCRIBER_ENGINES", "engine_status",
]

TRANSCRIBER_ENGINES = ["faster-whisper", "whisper.cpp", "parakeet.cpp"]

DIARIZER_ENGINE = "pyannote"


def make_transcriber(preset: dict) -> Transcriber:
    """The Transcriber a Preset asks for."""
    engine = preset.get("engine")
    model_path = preset.get("model_path")
    if not model_path:
        raise ValueError(f"Preset '{preset.get('id')}' has no model_path")

    if engine == "faster-whisper":
        from .faster_whisper import FasterWhisperTranscriber

        return FasterWhisperTranscriber(
            model_path=model_path,
            language=preset.get("language", "auto"),
            device=preset.get("device", "auto"),
            compute_type=preset.get("compute_type", "auto"),
            vad_filter=preset.get("vad_filter", True),
        )

    if engine == "whisper.cpp":
        from .whisper_cpp import WhisperCppTranscriber

        return WhisperCppTranscriber(
            cli_path=settings.whisper_cli_path,
            model_path=model_path,
            language=preset.get("language", "auto"),
        )

    if engine == "parakeet.cpp":
        from .parakeet_cpp import ParakeetCppTranscriber

        return ParakeetCppTranscriber(
            cli_path=settings.parakeet_cli_path,
            model_path=model_path,
            decoder=preset.get("decoder", "tdt"),
        )

    raise ValueError(f"Unknown transcription engine '{engine}'. Known: {TRANSCRIBER_ENGINES}")


def make_diarizer() -> Diarizer:
    """The Diarizer. There is only one, and swapping it means one more branch here."""
    from .pyannote import PyannoteDiarizer

    return PyannoteDiarizer()


def engine_status(preset: dict) -> dict:
    """Whether a Preset can actually run here — its CLI and its model must both exist.

    The UI greys out what it cannot run rather than letting the user queue a Job that
    is going to die in the worker.
    """
    engine = preset.get("engine")

    if engine == "faster-whisper":
        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            return {"available": False, "reason": "faster-whisper is not installed"}

        model_path = preset.get("model_path") or ""
        if not model_path:
            return {"available": False, "reason": "Missing model_path"}

        # If it is a local relative or absolute path, verify existence
        if (
            model_path.startswith(".")
            or model_path.startswith("/")
            or model_path.startswith("\\")
            or (len(model_path) > 1 and model_path[1] == ":")
        ):
            if not Path(model_path).exists():
                return {"available": False, "reason": f"Model not found at {model_path}"}

        return {"available": True, "reason": None}

    cli = {
        "whisper.cpp": settings.whisper_cli_path,
        "parakeet.cpp": settings.parakeet_cli_path,
    }.get(engine)

    if cli is None:
        return {"available": False, "reason": f"Unknown engine '{engine}'"}
    if not Path(cli).exists():
        return {"available": False, "reason": f"{engine} binary not found at {cli}"}

    model_path = preset.get("model_path") or ""
    if not Path(model_path).exists():
        return {"available": False, "reason": f"Model not found at {model_path}"}

    return {"available": True, "reason": None}
