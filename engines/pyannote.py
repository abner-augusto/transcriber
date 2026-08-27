"""pyannote as a Diarizer.

Runs locally: the HF token downloads the gated weights once, then inference happens
on this machine's GPU. See ADR-0001 — the token is a download credential, not a
data-sharing one. Do not remove it.

The pipeline is expensive to construct, so it is built once per process.
"""

import copy
import logging

import torch
import soundfile as sf

from preferences import get_secret, load_preferences

from .ports import Turn

log = logging.getLogger(__name__)

COMMUNITY_MODEL_ID = "pyannote/speaker-diarization-community-1"
FALLBACK_MODEL_ID = "pyannote/speaker-diarization-3.1"
TARGET_SAMPLE_RATE = 16000

# Optional diarization clustering overrides, read from preferences.json under
# "diarization". When nothing is set the pipeline keeps pyannote's own calibrated
# defaults. The clustering threshold is the main knob: lower splits more readily
# (one person can become several speakers), higher merges more readily. Fa/Fb are
# VBx-style and only some pipelines expose them — an unknown key is ignored below.
_CLUSTERING_PREF_TO_PARAM = {
    "clustering_threshold": "threshold",
    "Fa": "Fa",
    "Fb": "Fb",
}

# Distinct from None: "_sync_clustering_overrides has never run", vs. "ran, no overrides".
_UNSET = object()


class PyannoteDiarizer:
    _pipeline = None
    # The pretrained hyperparameters, captured once, so unsetting an override in the
    # UI restores the shipped values instead of stacking on the last override.
    _default_params = None
    # The override dict last handed to instantiate(). _UNSET means "never synced
    # yet"; {} is a real state meaning "running on defaults".
    _applied_overrides = _UNSET

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

            try:
                cls._default_params = copy.deepcopy(
                    dict(cls._pipeline.parameters(instantiated=True))
                )
            except Exception as e:
                log.warning(f"[pyannote] Could not read pipeline defaults ({e})")

            if torch.cuda.is_available():
                torch.backends.cuda.matmul.allow_tf32 = True
                torch.backends.cudnn.allow_tf32 = True
                cls._pipeline.to(torch.device("cuda"))
            elif torch.backends.mps.is_available():
                cls._pipeline.to(torch.device("mps"))

        cls._sync_clustering_overrides()
        return cls._pipeline

    @classmethod
    def _sync_clustering_overrides(cls):
        """Re-read preferences.json and re-instantiate if the clustering knobs changed.

        Runs on every get_pipeline() call, not just at build time — the Celery worker
        is a long-lived process, so a slider change in the UI has to reach the already
        cached pipeline. instantiate() only sets hyperparameters (no model reload), so
        calling it again is cheap; the equality check keeps it to actual changes.

        A missing / empty "diarization" block restores the shipped defaults. Any
        failure is logged and swallowed — a bad override must not stop diarization.
        """
        if cls._default_params is None:
            return

        cfg = load_preferences().get("diarization") or {}
        overrides = {
            param: float(cfg[pref])
            for pref, param in _CLUSTERING_PREF_TO_PARAM.items()
            if cfg.get(pref) is not None
        }
        if overrides == cls._applied_overrides:
            return
        had_overrides = bool(cls._applied_overrides) and cls._applied_overrides is not _UNSET

        try:
            params = copy.deepcopy(cls._default_params)
            params.setdefault("clustering", {}).update(overrides)
            cls._pipeline.instantiate(params)
            cls._applied_overrides = overrides
            if overrides:
                log.info(f"[pyannote] Applied clustering overrides {overrides}")
            elif had_overrides:
                log.info("[pyannote] Cleared clustering overrides; using pipeline defaults")
        except Exception as e:
            log.warning(
                f"[pyannote] Could not apply clustering overrides {overrides} ({e}); "
                "keeping current params"
            )

    def diarize(
        self,
        audio_path: str,
        min_speakers: int | None = None,
        max_speakers: int | None = None,
    ) -> list[Turn]:
        pipeline = self.get_pipeline()

        try:
            clustering = dict(pipeline.parameters(instantiated=True).get("clustering", {}))
            has_override = bool(self._applied_overrides) and self._applied_overrides is not _UNSET
            source = "override" if has_override else "default"
            log.info(
                f"[pyannote] diarizing with clustering={clustering} ({source}), "
                f"min_speakers={min_speakers}, max_speakers={max_speakers}"
            )
        except Exception:
            pass

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
