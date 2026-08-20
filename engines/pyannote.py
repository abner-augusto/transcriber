"""pyannote as a Diarizer.

Runs locally: the HF token downloads the gated weights once, then inference happens
on this machine's GPU. See ADR-0001 — the token is a download credential, not a
data-sharing one. Do not remove it.

The pipeline is expensive to construct, so it is built once per process.
"""

import logging

import torch
import soundfile as sf

from preferences import get_secret

from .ports import Turn

log = logging.getLogger(__name__)

COMMUNITY_MODEL_ID = "pyannote/speaker-diarization-community-1"
FALLBACK_MODEL_ID = "pyannote/speaker-diarization-3.1"
TARGET_SAMPLE_RATE = 16000


class PyannoteDiarizer:
    _pipeline = None

    @classmethod
    def get_pipeline(cls):
        if cls._pipeline is None:
            from pyannote.audio import Pipeline

            kwargs = {}
            token = get_secret("hf_auth_token")
            if token:
                kwargs["token"] = token

            try:
                cls._pipeline = Pipeline.from_pretrained(COMMUNITY_MODEL_ID, **kwargs)
                log.info(f"[pyannote] Loaded {COMMUNITY_MODEL_ID}")
            except Exception as e:
                log.warning(
                    f"[pyannote] Could not load {COMMUNITY_MODEL_ID} ({e}); falling back to {FALLBACK_MODEL_ID}"
                )
                cls._pipeline = Pipeline.from_pretrained(FALLBACK_MODEL_ID, **kwargs)
                log.info(f"[pyannote] Loaded fallback {FALLBACK_MODEL_ID}")

            if torch.cuda.is_available():
                torch.backends.cuda.matmul.allow_tf32 = True
                torch.backends.cudnn.allow_tf32 = True
                cls._pipeline.to(torch.device("cuda"))
            elif torch.backends.mps.is_available():
                cls._pipeline.to(torch.device("mps"))
        return cls._pipeline

    def diarize(
        self,
        audio_path: str,
        min_speakers: int | None = None,
        max_speakers: int | None = None,
    ) -> list[Turn]:
        pipeline = self.get_pipeline()

        waveform, sample_rate = _load_audio_tensor(audio_path)
        audio_input = {"waveform": waveform, "sample_rate": sample_rate}

        kwargs = {}
        if min_speakers is not None:
            kwargs["min_speakers"] = min_speakers
        if max_speakers is not None:
            kwargs["max_speakers"] = max_speakers

        result = pipeline(audio_input, **kwargs)

        # pyannote v4 returns DiarizeOutput with .speaker_diarization Annotation or .serialize()
        if hasattr(result, "speaker_diarization"):
            annotation = result.speaker_diarization
            turns = [
                Turn(start=round(turn.start, 3), end=round(turn.end, 3), speaker=speaker)
                for turn, _, speaker in annotation.itertracks(yield_label=True)
            ]
        elif hasattr(result, "serialize"):
            turns = [Turn.from_dict(t) for t in result.serialize().get("diarization", [])]
        else:
            # pyannote v3 returns an Annotation
            turns = [
                Turn(start=round(turn.start, 3), end=round(turn.end, 3), speaker=speaker)
                for turn, _, speaker in result.itertracks(yield_label=True)
            ]

        log.info(f"[pyannote] {len(turns)} turns, {len({t.speaker for t in turns})} speakers")
        return turns


def _load_audio_tensor(path: str, target_sr: int = TARGET_SAMPLE_RATE):
    """Load audio into the (channels, samples) float32 tensor pyannote expects."""
    data, sr = sf.read(path, dtype="float32", always_2d=True)
    # soundfile gives (samples, channels) — pyannote wants it the other way round.
    waveform = torch.from_numpy(data.T)
    if sr != target_sr:
        import torchaudio.functional as F

        waveform = F.resample(waveform, sr, target_sr)
        sr = target_sr
    return waveform, sr
