import torch
import numpy as np
import soundfile as sf
from config import settings
from preferences import get_secret


def _load_audio_tensor(path: str, target_sr: int = 16000):
    """Load audio file to a (channels, samples) float32 tensor via soundfile,
    resampling to target_sr with scipy if needed."""
    data, sr = sf.read(path, dtype="float32", always_2d=True)
    # soundfile returns (samples, channels) — transpose to (channels, samples)
    waveform = torch.from_numpy(data.T)
    if sr != target_sr:
        import torchaudio.functional as F
        waveform = F.resample(waveform, sr, target_sr)
        sr = target_sr
    return waveform, sr


class DiarizationService:
    _pipeline = None

    @classmethod
    def get_pipeline(cls):
        if cls._pipeline is None:
            from pyannote.audio import Pipeline
            kwargs = {}
            token = get_secret("hf_auth_token")
            if token:
                kwargs["token"] = token

            cls._pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                **kwargs,
            )
            if torch.cuda.is_available():
                cls._pipeline.to(torch.device("cuda"))
            elif torch.backends.mps.is_available():
                cls._pipeline.to(torch.device("mps"))
        return cls._pipeline

    def diarize(
        self,
        audio_path: str,
        min_speakers: int | None = None,
        max_speakers: int | None = None,
    ) -> list[dict]:
        """
        Run speaker diarization on audio file.
        Returns list of {start, end, speaker} dicts.
        """
        pipeline = self.get_pipeline()

        waveform, sr = _load_audio_tensor(audio_path)
        audio_input = {"waveform": waveform, "sample_rate": sr}

        kwargs = {}
        if min_speakers is not None:
            kwargs["min_speakers"] = min_speakers
        if max_speakers is not None:
            kwargs["max_speakers"] = max_speakers

        result = pipeline(audio_input, **kwargs)

        # pyannote v4 returns DiarizeOutput with .serialize()
        if hasattr(result, "serialize"):
            data = result.serialize()
            return data.get("diarization", [])

        # pyannote v3 fallback
        segments = []
        for turn, _, speaker in result.itertracks(yield_label=True):
            segments.append({
                "start": round(turn.start, 3),
                "end": round(turn.end, 3),
                "speaker": speaker,
            })
        return segments
