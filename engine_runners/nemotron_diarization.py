"""Offline adapter for NVIDIA Nemotron 3 Diarization."""

from __future__ import annotations

import subprocess
import os
from pathlib import Path

os.environ["HF_HUB_OFFLINE"] = "1"

import numpy as np
import torch
from transformers import AutoModelForAudioFrameClassification, AutoProcessor

from engines.ports import Turn
from engine_runtimes.protocol import EngineRequest
from ._main import run


class NemotronDiarization:
    def __init__(self, request: EngineRequest):
        self.request = request
        self.processor = None
        self.model = None

    def load(self) -> None:
        self.processor = AutoProcessor.from_pretrained(self.request.model_path, local_files_only=True)
        self.model = AutoModelForAudioFrameClassification.from_pretrained(
            self.request.model_path, local_files_only=True
        ).to(self.request.device).eval()

    def diarize(self, audio_path: str) -> list[Turn]:
        if self.model is None or self.processor is None:
            self.load()
        result = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(Path(audio_path)), "-f", "f32le", "-ac", "1", "-ar", "16000", "-"],
            capture_output=True, check=True,
        )
        audio = np.frombuffer(result.stdout, dtype=np.float32)
        inputs = self.processor(audio, sampling_rate=16000).to(self.request.device, dtype=self.model.dtype)
        with torch.inference_mode():
            logits = self.model(**inputs).logits
        segments = self.processor.extract_speaker_dict(
            logits, inputs.attention_mask, threshold=float(self.request.options.get("threshold", 0.5))
        )[0]
        return [Turn(s["Start"], s["End"], f"SPEAKER_{s['Speaker']:02d}")
                for s in segments if s["End"] > s["Start"]]


def main() -> int:
    return run("nemotron-3-diarization", lambda request: NemotronDiarization(request))


if __name__ == "__main__":
    raise SystemExit(main())
