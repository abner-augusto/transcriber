"""CTC Forced Alignment Engine.

Refines Word-level timestamps from ASR (Whisper / Parakeet) by aligning audio against
the recognized text using a CTC acoustic model.

Model:
    Uses Meta's MMS Forced Alignment model (torchaudio.pipelines.MMS_FA), which supports
    over 1,100 languages including Portuguese (pt-BR / pt) using character-level romanized CTC tokens.

Lifecycle & Constraints:
    - Model weights are loaded locally and cached as a process singleton.
    - Runs on GPU (CUDA/MPS) if available, or CPU.
    - Follows ADR-0001: strictly local inference, no cloud calls.
    - Words retain their exact text, casing, punctuation, and ordering.
    - Explicit fallback policy: if alignment fails or cannot be computed for any window,
      the engine logs a warning and falls back to original timestamps without dropping words.
"""

import logging
import unicodedata
from typing import Optional

import numpy as np
import soundfile as sf
import torch

from config import settings
from . import validate_alignment_engine
from .ports import Aligner, Word

log = logging.getLogger(__name__)

TARGET_SAMPLE_RATE = 16000
MAX_WINDOW_DURATION = 25.0
PAUSE_SPLIT_THRESHOLD = 0.8
WINDOW_PADDING_SECONDS = 0.2


def normalize_token_text(text: str, dictionary: dict[str, int]) -> list[int]:
    """Extract CTC token IDs for a word after unicode accent decomposition and casing normalization.

    Punctuation and symbols not in the dictionary are excluded from CTC alignment tokens,
    while preserving the actual Word.text untouched.
    """
    stripped = text.strip()
    if not stripped:
        return []

    # Decompose unicode characters (e.g., 'á' -> 'a' + combining acute)
    normalized = "".join(
        c for c in unicodedata.normalize("NFKD", stripped)
        if not unicodedata.combining(c)
    ).lower()

    # Match against dictionary characters (excluding blank/separator '-')
    tokens = [dictionary[c] for c in normalized if c in dictionary and c != "-"]
    return tokens


class MMSCTCAligner:
    """CTC forced aligner based on torchaudio MMS_FA."""

    _bundle = None
    _model = None
    _aligner = None
    _dict = None
    _device = None

    def __init__(self, device: Optional[str] = None):
        self.requested_device = device

    @classmethod
    def get_bundle(cls):
        if cls._bundle is None:
            import torchaudio.pipelines as pipelines
            cls._bundle = pipelines.MMS_FA
        return cls._bundle

    @classmethod
    def get_model_and_aligner(cls, device_str: Optional[str] = None):
        if cls._model is None:
            bundle = cls.get_bundle()
            model = bundle.get_model()

            if device_str and device_str != "auto":
                device = torch.device(device_str)
            elif torch.cuda.is_available():
                device = torch.device("cuda")
            elif torch.backends.mps.is_available():
                device = torch.device("mps")
            else:
                device = torch.device("cpu")

            model.to(device)
            model.eval()

            cls._model = model
            cls._aligner = bundle.get_aligner()
            cls._dict = bundle.get_dict()
            cls._device = device
            log.info(f"[alignment] Loaded MMS_FA model on device {device}")

        return cls._model, cls._aligner, cls._dict, cls._device

    def align(self, audio_path: str, words: list[Word]) -> list[Word]:
        """Align existing Words against audio, updating start and end timestamps.

        Guarantees:
        - Word count and order are preserved.
        - Word.text is preserved verbatim.
        - On failure or error, falls back to original words.
        """
        if not words:
            return []

        try:
            waveform, sample_rate, duration = self._load_audio(audio_path)
        except Exception as e:
            log.warning(f"[alignment] Failed to load audio '{audio_path}' ({e}); falling back to original timestamps")
            return words

        try:
            model, aligner, dictionary, device = self.get_model_and_aligner(self.requested_device)
        except Exception as e:
            log.warning(f"[alignment] Failed to load MMS_FA model ({e}); falling back to original timestamps")
            return words

        # Group words into contiguous time windows for safe and efficient alignment
        windows = self._build_windows(words, duration)
        aligned_words = list(words)  # shallow copy to replace modified Word instances

        aligned_count = 0
        failed_window = False
        for win_start_idx, win_end_idx, win_start_time, win_end_time in windows:
            window_words = words[win_start_idx:win_end_idx]
            try:
                refined = self._align_window(
                    waveform=waveform,
                    sample_rate=sample_rate,
                    words=window_words,
                    window_start=win_start_time,
                    window_end=win_end_time,
                    model=model,
                    aligner=aligner,
                    dictionary=dictionary,
                    device=device,
                )
                for idx_offset, ref_w in enumerate(refined):
                    aligned_words[win_start_idx + idx_offset] = ref_w
                    if ref_w.start != window_words[idx_offset].start or ref_w.end != window_words[idx_offset].end:
                        aligned_count += 1
            except Exception as e:
                failed_window = True
                log.warning(
                    f"[alignment] Window [{win_start_time:.2f}s - {win_end_time:.2f}s] failed ({e}); "
                    "falling back to original timestamps for all Words"
                )

        if failed_window:
            return words
        # Ensure monotonicity and non-negative boundaries across all words
        validated_words = self._enforce_monotonicity(aligned_words, duration)
        log.info(f"[alignment] Refined timestamps for {aligned_count}/{len(words)} words in {len(windows)} windows")
        return validated_words

    def _load_audio(self, audio_path: str) -> tuple[torch.Tensor, int, float]:
        """Load audio file as mono float32 tensor at TARGET_SAMPLE_RATE."""
        data, sr = sf.read(audio_path, dtype="float32", always_2d=True)
        # Average channels to mono
        mono_data = data.mean(axis=1) if data.shape[1] > 1 else data[:, 0]
        waveform = torch.from_numpy(mono_data).unsqueeze(0)  # (1, num_samples)

        if sr != TARGET_SAMPLE_RATE:
            import torchaudio.functional as F
            waveform = F.resample(waveform, sr, TARGET_SAMPLE_RATE)
            sr = TARGET_SAMPLE_RATE

        duration = waveform.shape[1] / sr
        return waveform, sr, duration

    def _build_windows(self, words: list[Word], total_duration: float) -> list[tuple[int, int, float, float]]:
        """Split words into manageable temporal windows based on pauses or duration."""
        windows = []
        start_idx = 0

        while start_idx < len(words):
            end_idx = start_idx + 1
            first_w = words[start_idx]

            while end_idx < len(words):
                curr_w = words[end_idx]
                prev_w = words[end_idx - 1]

                # Split on significant pause or exceeding max window duration
                pause = curr_w.start - prev_w.end
                span_duration = curr_w.end - first_w.start

                if pause >= PAUSE_SPLIT_THRESHOLD or span_duration >= MAX_WINDOW_DURATION:
                    break
                end_idx += 1

            win_start = max(0.0, words[start_idx].start - WINDOW_PADDING_SECONDS)
            win_end = min(total_duration, words[end_idx - 1].end + WINDOW_PADDING_SECONDS)
            windows.append((start_idx, end_idx, win_start, win_end))
            start_idx = end_idx

        return windows

    def _align_window(
        self,
        waveform: torch.Tensor,
        sample_rate: int,
        words: list[Word],
        window_start: float,
        window_end: float,
        model,
        aligner,
        dictionary: dict[str, int],
        device: torch.device,
    ) -> list[Word]:
        """Align words within a single audio window."""
        start_sample = int(window_start * sample_rate)
        end_sample = int(window_end * sample_rate)
        audio_slice = waveform[:, start_sample:end_sample]

        if audio_slice.shape[1] < int(0.1 * sample_rate):
            return list(words)

        # Extract tokens for each word
        token_lists = [normalize_token_text(w.text, dictionary) for w in words]

        # Track words that have alignable characters
        alignable_indices = [i for i, tokens in enumerate(token_lists) if len(tokens) > 0]
        if not alignable_indices:
            return list(words)

        alignable_tokens = [token_lists[i] for i in alignable_indices]

        # Model inference
        audio_tensor = audio_slice.to(device)
        with torch.inference_mode():
            emission, _ = model(audio_tensor)

        emission_frames = emission.shape[1]
        total_tokens = sum(len(t) for t in alignable_tokens)

        # MMS_FA CTC aligner requires emission_frames >= total_tokens
        if emission_frames < total_tokens:
            return list(words)

        # Compute CTC alignment spans
        spans = aligner(emission[0], alignable_tokens)

        frame_duration = (audio_slice.shape[1] / sample_rate) / emission_frames
        result = list(words)

        for span_idx, word_idx in enumerate(alignable_indices):
            word_span = spans[span_idx]
            if not word_span:
                continue

            frame_start = word_span[0].start
            frame_end = word_span[-1].end

            refined_start = round(window_start + (frame_start * frame_duration), 3)
            refined_end = round(window_start + (frame_end * frame_duration), 3)

            # Safeguard span bounds
            refined_start = max(0.0, refined_start)
            refined_end = max(refined_start, refined_end)

            avg_score = sum(getattr(t, "score", 0.0) for t in word_span) / len(word_span)
            confidence = round(float(avg_score), 4) if words[word_idx].confidence is None else words[word_idx].confidence

            result[word_idx] = Word(
                start=refined_start,
                end=refined_end,
                text=words[word_idx].text,
                confidence=confidence,
            )

        return result

    def _enforce_monotonicity(self, words: list[Word], total_duration: float) -> list[Word]:
        """Ensure start <= end and timestamps do not regress chronologically."""
        if not words:
            return []

        adjusted = []
        prev_start = 0.0

        for w in words:
            start = max(0.0, w.start)
            if start < prev_start:
                start = prev_start
            end = max(start, w.end)
            if total_duration > 0:
                end = min(total_duration, end)

            adjusted.append(Word(
                start=start,
                end=end,
                text=w.text,
                confidence=w.confidence,
            ))
            prev_start = start

        return adjusted


def make_aligner(preset_or_config: Optional[dict] = None) -> Aligner:
    """Instantiate a configured Aligner."""
    device = None
    model = settings.forced_alignment_model
    if preset_or_config:
        device = preset_or_config.get("device")
        model = preset_or_config.get("model", model)
    validate_alignment_engine(model)
    return MMSCTCAligner(device=device)


def align_words(audio_path: str, words: list[Word], config: Optional[dict] = None) -> list[Word]:
    """Refine timestamps of Words against audio using CTC forced alignment.

    If alignment is disabled, unavailable, or encounters an error, returns the original
    Words without modifying text, ordering, or timestamps.
    """
    if not words:
        return []

    aligner = make_aligner(config)
    return aligner.align(audio_path, words)


def alignment_engine_status(config: Optional[dict] = None) -> dict:
    """Check availability of the forced alignment dependencies and model."""
    model = settings.forced_alignment_model
    if config:
        model = config.get("model", model)
    try:
        validate_alignment_engine(model)
    except ValueError as exc:
        return {"available": False, "engine": model, "description": "Unsupported alignment engine", "reason": str(exc)}
    try:
        import torchaudio.pipelines as pipelines  # noqa: F401
        return {
            "available": True,
            "engine": "mms-fa",
            "description": "Meta MMS Multilingual CTC Forced Aligner (pt-BR compatible)",
            "reason": None,
        }
    except Exception as e:
        return {
            "available": False,
            "engine": "mms-fa",
            "description": "Meta MMS Multilingual CTC Forced Aligner (pt-BR compatible)",
            "reason": str(e),
        }
