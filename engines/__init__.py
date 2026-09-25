"""Engines: the interchangeable half of the pipeline.

A Preset names an Engine ("whisper.cpp") and the model to run on it. This registry
turns that name into an adapter. Adding an Engine is therefore two files — an adapter
here and a Preset JSON in model_presets/ — and nothing in tasks/ changes.

Imports of the adapters are deferred: the API process lists Presets without paying
for torch, and a machine with no parakeet build can still run whisper.
"""

from .ports import (
    DiarizationResult,
    Aligner,
    Diarizer,
    Transcriber,
    Transcription,
    Turn,
    Word,
    raw_transcription,
)
from .overlap import compute_overlaps


__all__ = [
    "Word", "Turn", "DiarizationResult", "Transcription", "raw_transcription",
    "Transcriber", "Diarizer", "Aligner",
    "make_transcriber", "make_diarizer", "make_aligner", "align_words",
    "TRANSCRIBER_ENGINES", "ALIGNMENT_ENGINES", "compute_overlaps", "probe_engine", "engine_status", "alignment_engine_status",
    "release_gpu_memory", "unload_all_engines",
]

TRANSCRIBER_ENGINES = ["faster-whisper", "whisper.cpp", "parakeet.cpp", "qwen3-asr", "vibevoice"]

ALIGNMENT_ENGINES = ["mms-fa"]

DIARIZER_ENGINE = "pyannote"


def validate_alignment_engine(engine: str | None) -> str:
    """Return a supported alignment engine or fail with an actionable message."""
    from config import settings

    selected = engine or settings.forced_alignment_model
    if selected not in ALIGNMENT_ENGINES:
        raise ValueError(f"Unknown alignment engine '{selected}'. Known: {', '.join(ALIGNMENT_ENGINES)}")
    return selected


def make_transcriber(preset: dict) -> Transcriber:
    """The Transcriber a Preset asks for."""
    from config import settings

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
            condition_on_previous_text=preset.get("condition_on_previous_text", False),
            repetition_penalty=preset.get("repetition_penalty", 1.1),
        )

    if engine == "whisper.cpp":
        from .whisper_cpp import WhisperCppTranscriber
        from preferences import load_preferences

        prefs = load_preferences()
        whisper_dtw_pref = prefs.get("whisper_dtw", {})

        dtw_enabled = preset.get(
            "dtw",
            whisper_dtw_pref.get("enabled", settings.whisper_dtw_enabled)
            if isinstance(whisper_dtw_pref, dict)
            else settings.whisper_dtw_enabled,
        )
        dtw_preset = preset.get(
            "dtw_preset",
            whisper_dtw_pref.get("preset", settings.whisper_dtw_preset)
            if isinstance(whisper_dtw_pref, dict)
            else settings.whisper_dtw_preset,
        )

        return WhisperCppTranscriber(
            cli_path=settings.whisper_cli_path,
            model_path=model_path,
            language=preset.get("language", "auto"),
            dtw_enabled=bool(dtw_enabled),
            dtw_preset=dtw_preset or None,
        )

    if engine == "parakeet.cpp":
        from .parakeet_cpp import ParakeetCppTranscriber

        return ParakeetCppTranscriber(
            cli_path=settings.parakeet_cli_path,
            model_path=model_path,
            decoder=preset.get("decoder"),
            language=preset.get("language", "auto"),
        )

    if engine == "qwen3-asr":
        from .isolated_python import IsolatedPythonTranscriber

        return IsolatedPythonTranscriber(engine_id=engine,
            model_path=model_path,
            aligner_path=preset.get("aligner_path"),
            device=preset.get("device", "cuda"),
            options={"language": preset.get("language", "Portuguese"), "chunk_seconds": float(preset.get("chunk_seconds", 300.0)), "overlap_seconds": float(preset.get("overlap_seconds", 30.0))},
        )

    if engine == "vibevoice":
        from .isolated_python import IsolatedPythonTranscriber

        return IsolatedPythonTranscriber(engine_id=engine,
            model_path=model_path,
            aligner_path=preset.get("aligner_path"),
            device=preset.get("device", "cuda"),
            options={"window_seconds": float(preset.get("window_seconds", 600.0)), "overlap_seconds": float(preset.get("overlap_seconds", 45.0)), "quantization": preset.get("quantization", "nf4")},
        )

    raise ValueError(f"Unknown transcription engine '{engine}'. Known: {TRANSCRIBER_ENGINES}")


def make_diarizer() -> Diarizer:
    """The Diarizer. There is only one, and swapping it means one more branch here."""
    from .pyannote import PyannoteDiarizer

    return PyannoteDiarizer()


def engine_status(preset: dict) -> dict:
    """Return structured Engine health plus the legacy availability fields."""
    return probe_engine(preset).to_dict()


def probe_engine(preset: dict, deep: bool = False):
    from .health import probe_engine as _probe

    return _probe(preset, deep=deep)


def make_aligner(config: dict | None = None) -> Aligner:
    """The Aligner. Uses CTC forced alignment to refine Word timestamps."""
    from .alignment import make_aligner as _make_aligner

    return _make_aligner(config)


def align_words(audio_path: str, words: list[Word], config: dict | None = None) -> list[Word]:
    """Align Words against audio using CTC forced alignment with graceful fallback."""
    from .alignment import align_words as _align_words

    return _align_words(audio_path, words, config)


def alignment_engine_status(config: dict | None = None) -> dict:
    """Check availability of the forced alignment engine."""
    from .alignment import alignment_engine_status as _status

    return _status(config)


def release_gpu_memory() -> None:
    """Run garbage collection and flush CUDA / MPS caching allocators."""
    from .gpu_memory import release_gpu_memory as _release

    return _release()


def unload_all_engines() -> None:
    """Unload all resident models (Faster-Whisper, Pyannote, MMS-FA, ECAPA-TDNN) and flush GPU memory."""
    from .gpu_memory import unload_all_engines as _unload

    return _unload()
