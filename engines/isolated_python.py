"""Thin core adapters for Python Engines hosted in dedicated interpreters."""

import logging
from pathlib import Path

from config import engine_runtime_python, settings
from engine_runtimes import EngineRequest, launch_engine
from engine_runtimes.manifest import runtime_for_engine
from .overlap import compute_exclusive_turns
from .ports import DiarizationResult, Transcription

log = logging.getLogger(__name__)

# A Speaker with less total speech than this across the whole Meeting is dropped.
# Nemotron can open a speaker channel for a few seconds of echo or crosstalk (the
# 2026-09-25 bench found 3.6 s on a dual-track system track); that Speaker would get
# no Words and surface as an empty "Participant N".
MIN_SPEAKER_SECONDS = 5.0


class IsolatedPythonTranscriber:
    def __init__(self, *, engine_id: str, model_path: str, aligner_path: str | None,
                 device: str, options: dict):
        self.engine_id, self.model_path, self.aligner_path = engine_id, model_path, aligner_path
        self.device, self.options = device, options
    def _request(self, *, operation: str, audio_path: str, vocabulary: str | None = None):
        python = engine_runtime_python(runtime_for_engine(self.engine_id))
        request = EngineRequest.from_dict({"schema_version": 1, "operation": operation, "engine_id": self.engine_id,
            "audio_path": str(Path(audio_path).resolve()), "vocabulary": vocabulary,
            "model_path": str(Path(self.model_path).resolve()),
            "aligner_path": str(Path(self.aligner_path).resolve()) if self.aligner_path else None,
            "device": self.device, "options": self.options})
        response = launch_engine(python=python, module=f"engine_runners.{self.engine_id.replace('-', '_')}",
            request=request, timeout=settings.engine_runtime_timeout_seconds,
            debug_directory=settings.engine_runtime_debug_directory or None)
        return response

    def load(self) -> None:
        response = self._request(operation="load", audio_path=str(Path(self.model_path).resolve()))
        if response.words or response.native_turns:
            raise RuntimeError("load-only engine response unexpectedly contained transcription data")

    def transcribe(self, audio_path: str, vocabulary: str | None = None) -> Transcription:
        response = self._request(operation="transcribe", audio_path=audio_path, vocabulary=vocabulary)
        native = (
            DiarizationResult(turns=list(response.native_turns), engine=self.engine_id)
            if response.native_turns is not None
            else None
        )
        return Transcription(
            words=list(response.words),
            native=native,
            provenance={
                "runtime": {
                    "fingerprint": response.runtime_fingerprint,
                    "diagnostics": dict(response.diagnostics),
                }
            },
        )


class IsolatedPythonDiarizer:
    """Nemotron 3 Diarization, run in its dedicated runtime."""

    engine_id = "nemotron-3-diarization"

    def __init__(self, *, model_path: str, device: str, threshold: float = 0.5):
        self.model_path, self.device = model_path, device
        self.options = {"threshold": threshold}

    def _request(self, operation: str, audio_path: str):
        request = EngineRequest.from_dict({"schema_version": 1, "operation": operation,
            "engine_id": self.engine_id, "audio_path": str(Path(audio_path).resolve()),
            "vocabulary": None, "model_path": str(Path(self.model_path).resolve()),
            "aligner_path": None, "device": self.device, "options": self.options})
        return launch_engine(python=engine_runtime_python(runtime_for_engine(self.engine_id)),
            module="engine_runners.nemotron_diarization", request=request,
            timeout=settings.engine_runtime_timeout_seconds,
            debug_directory=settings.engine_runtime_debug_directory or None)

    def load(self) -> None:
        response = self._request("load", self.model_path)
        if response.words or response.native_turns:
            raise RuntimeError("load-only engine response unexpectedly contained diarization data")

    def diarize(self, audio_path: str, min_speakers=None, max_speakers=None) -> DiarizationResult:
        """Turns in arrival order. The model finds up to 8 Speakers on its own."""
        if min_speakers is not None or max_speakers is not None:
            log.info("[nemotron] ignores min_speakers=%s and max_speakers=%s; it finds up to 8",
                     min_speakers, max_speakers)
        turns = list(self._request("diarize", audio_path).native_turns or ())
        speech: dict[str, float] = {}
        for turn in turns:
            speech[turn.speaker] = speech.get(turn.speaker, 0.0) + turn.end - turn.start
        dropped = {speaker for speaker, seconds in speech.items() if seconds < MIN_SPEAKER_SECONDS}
        if dropped:
            log.info("[nemotron] dropped %s: under %.0f s of speech", sorted(dropped), MIN_SPEAKER_SECONDS)
        turns = [turn for turn in turns if turn.speaker not in dropped]
        return DiarizationResult(turns, exclusive_turns=compute_exclusive_turns(turns), engine=self.engine_id)
