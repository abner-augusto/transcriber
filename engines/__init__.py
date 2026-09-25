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

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from run_config import RunConfig


__all__ = [
    "Word", "Turn", "DiarizationResult", "Transcription", "raw_transcription",
    "Transcriber", "Diarizer", "Aligner",
    "make_transcriber", "make_diarizer", "make_aligner", "align_words",
    "TRANSCRIBER_ENGINES", "ALIGNMENT_ENGINES", "compute_overlaps", "probe_engine", "engine_status", "alignment_engine_status",
]

TRANSCRIBER_ENGINES = ["faster-whisper", "whisper.cpp", "parakeet.cpp", "qwen3-asr", "vibevoice"]

DEFAULT_ALIGNMENT_ENGINE = "mms-fa"
ALIGNMENT_ENGINES = [DEFAULT_ALIGNMENT_ENGINE]

DIARIZER_ENGINE = "pyannote"


def validate_alignment_engine(engine: str | None) -> str:
    """Return a supported alignment engine or fail with an actionable message."""
    selected = engine or DEFAULT_ALIGNMENT_ENGINE
    if selected not in ALIGNMENT_ENGINES:
        raise ValueError(f"Unknown alignment engine '{selected}'. Known: {', '.join(ALIGNMENT_ENGINES)}")
    return selected


def _alignment_config(run_config: "RunConfig") -> dict | None:
    alignment = run_config.forced_alignment
    return alignment.model_dump() if alignment is not None else None


def make_transcriber(run_config: "RunConfig") -> Transcriber:
    """Build the Transcriber selected by a Job's resolved RunConfig."""
    from config import settings

    preset = run_config.preset
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

        return WhisperCppTranscriber(
            cli_path=settings.whisper_cli_path,
            model_path=model_path,
            language=preset.get("language", "auto"),
            dtw_enabled=run_config.whisper_dtw.enabled,
            dtw_preset=run_config.whisper_dtw.preset or None,
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


def make_diarizer(run_config: "RunConfig", *, hf_token: str = "") -> Diarizer:
    """The Diarizer. There is only one, and swapping it means one more branch here."""
    from .pyannote import PyannoteDiarizer

    return PyannoteDiarizer(
        clustering=run_config.diarization.model_dump(exclude_none=True),
        auth_token=hf_token,
    )


def engine_status(preset: dict) -> dict:
    """Return structured Engine health plus the legacy availability fields."""
    return probe_engine(preset).to_dict()


def probe_engine(preset: dict, deep: bool = False):
    from .health import probe_engine as _probe

    return _probe(preset, deep=deep)


def make_aligner(run_config: "RunConfig") -> Aligner:
    """The Aligner. Uses CTC forced alignment to refine Word timestamps."""
    from .alignment import make_aligner as _make_aligner

    return _make_aligner(_alignment_config(run_config))


def align_words(audio_path: str, words: list[Word], run_config: "RunConfig | None" = None) -> list[Word]:
    """Align Words against audio using CTC forced alignment with graceful fallback."""
    from .alignment import align_words as _align_words

    return _align_words(audio_path, words, _alignment_config(run_config) if run_config else None)


def alignment_engine_status(config: dict | None = None) -> dict:
    """Check availability of the forced alignment engine."""
    from .alignment import alignment_engine_status as _status

    return _status(config)