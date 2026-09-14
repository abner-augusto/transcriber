"""Thin core adapters for Python Engines hosted in dedicated interpreters."""

from pathlib import Path

from config import settings
from engine_runtimes import EngineRequest, launch_engine
from .ports import DiarizationResult, Word


class IsolatedPythonTranscriber:
    def __init__(self, *, engine_id: str, model_path: str, aligner_path: str | None,
                 device: str, options: dict):
        self.engine_id, self.model_path, self.aligner_path = engine_id, model_path, aligner_path
        self.device, self.options = device, options
        self.has_native_diarization = engine_id == "vibevoice"
        self._native_diarization = None
        self.runtime_fingerprint = None
        self.runtime_diagnostics = {}

    def get_native_diarization(self):
        return self._native_diarization

    def transcribe(self, audio_path: str, vocabulary: str | None = None) -> list[Word]:
        python = settings.qwen3_asr_python if self.engine_id == "qwen3-asr" else settings.vibevoice_python
        request = EngineRequest.from_dict({"schema_version": 1, "engine_id": self.engine_id,
            "audio_path": str(Path(audio_path).resolve()), "vocabulary": vocabulary,
            "model_path": str(Path(self.model_path).resolve()),
            "aligner_path": str(Path(self.aligner_path).resolve()) if self.aligner_path else None,
            "device": self.device, "options": self.options})
        response = launch_engine(python=python, module=f"engine_runners.{self.engine_id.replace('-', '_')}",
            request=request, timeout=settings.engine_runtime_timeout_seconds,
            debug_directory=settings.engine_runtime_debug_directory or None)
        self.runtime_fingerprint = response.runtime_fingerprint
        self.runtime_diagnostics = dict(response.diagnostics)
        if response.native_turns is not None:
            self._native_diarization = DiarizationResult(turns=list(response.native_turns))
        return list(response.words)
