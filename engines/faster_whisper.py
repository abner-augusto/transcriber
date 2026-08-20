"""faster-whisper as a Transcriber.

Runs Whisper models via CTranslate2 with optional GPU (CUDA) acceleration and
integrated Silero VAD. Models can be standard Whisper model names (e.g.
"large-v3", "large-v3-turbo", "medium"), Hugging Face repository IDs (e.g.
"inesc-id/WhisperLv3-X-PT-All"), or paths to local CTranslate2 models.
"""

import logging
from pathlib import Path

from .ports import Word

log = logging.getLogger(__name__)

MAX_PROMPT_CHARS = 500


class FasterWhisperTranscriber:
    _models: dict = {}

    def __init__(
        self,
        model_path: str,
        language: str = "auto",
        device: str = "auto",
        compute_type: str = "auto",
        vad_filter: bool = True,
        min_silence_duration_ms: int = 500,
        condition_on_previous_text: bool = False,
        repetition_penalty: float = 1.1,
    ):
        self.model_path = model_path
        self.language = language
        self.device = device
        self.compute_type = compute_type
        self.vad_filter = vad_filter
        self.min_silence_duration_ms = min_silence_duration_ms
        self.condition_on_previous_text = condition_on_previous_text
        self.repetition_penalty = repetition_penalty

    @classmethod
    def get_model(cls, model_path: str, device: str = "auto", compute_type: str = "auto"):
        cache_key = (model_path, device, compute_type)
        if cache_key not in cls._models:
            from faster_whisper import WhisperModel
            import torch

            resolved_device = device
            if resolved_device == "auto":
                resolved_device = "cuda" if torch.cuda.is_available() else "cpu"

            resolved_compute = compute_type
            if resolved_compute == "auto":
                resolved_compute = "float16" if resolved_device == "cuda" else "int8"

            log.info(
                f"[faster-whisper] Loading model '{model_path}' on {resolved_device} ({resolved_compute})"
            )
            cls._models[cache_key] = WhisperModel(
                model_path,
                device=resolved_device,
                compute_type=resolved_compute,
            )
        return cls._models[cache_key]

    def transcribe(self, audio_path: str, vocabulary: str | None = None) -> list[Word]:
        model = self.get_model(self.model_path, self.device, self.compute_type)

        lang = None if (not self.language or self.language == "auto") else self.language
        prompt = vocabulary[:MAX_PROMPT_CHARS] if vocabulary else None

        kwargs = {
            "language": lang,
            "initial_prompt": prompt,
            "word_timestamps": True,
            "vad_filter": self.vad_filter,
            "condition_on_previous_text": self.condition_on_previous_text,
            "repetition_penalty": self.repetition_penalty,
        }
        if self.vad_filter:
            kwargs["vad_parameters"] = dict(
                min_silence_duration_ms=self.min_silence_duration_ms
            )

        segments, info = model.transcribe(audio_path, **kwargs)
        words = parse_words_from_segments(segments)

        detected_lang = getattr(info, "language", self.language)
        lang_prob = getattr(info, "language_probability", 1.0)
        log.info(
            f"[faster-whisper] {len(words)} words transcribed from {self.model_path} "
            f"(lang: {detected_lang}, prob: {lang_prob:.2f})"
        )
        return words


def parse_words_from_segments(segments) -> list[Word]:
    """Extract join-ready Word objects from faster-whisper segments."""
    words: list[Word] = []
    for segment in segments:
        segment_words = getattr(segment, "words", None)
        if segment_words:
            for w in segment_words:
                text = getattr(w, "word", "")
                if not text:
                    continue
                stripped = text.strip()
                if (
                    stripped
                    and not text.startswith(" ")
                    and stripped not in {",", ".", "!", "?", ";", ":", "-", "—", ")", "]", "}", "...", "”", '"'}
                ):
                    text = " " + text

                w_start = round(float(w.start), 3)
                w_end = max(w_start, round(float(w.end), 3))
                conf = getattr(w, "probability", None)
                words.append(
                    Word(
                        start=w_start,
                        end=w_end,
                        text=text,
                        confidence=round(float(conf), 3) if conf is not None else None,
                    )
                )
        elif getattr(segment, "text", ""):
            text = segment.text
            if not text.startswith(" "):
                text = " " + text
            s_start = round(float(segment.start), 3)
            s_end = max(s_start, round(float(segment.end), 3))
            words.append(
                Word(
                    start=s_start,
                    end=s_end,
                    text=text,
                    confidence=None,
                )
            )
    return words
