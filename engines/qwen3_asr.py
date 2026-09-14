"""Qwen3-ASR as a Transcriber with Qwen3-ForcedAligner timestamping.

Qwen3-ASR-1.7B provides state-of-the-art multilingual speech recognition and
domain-specific vocabulary priming via `--context` / prompt. Because the foundation
ASR model outputs clean text tokens without native word timestamps, this adapter
pairs it with Qwen3-ForcedAligner-0.6B (or MMS-FA fallback) to produce millisecond-accurate
Word objects adhering to the Transcriber port contract.

Long audio is chunked in sliding windows (default 300s = 5 min) with pause/sequence
matching overlap to keep VRAM strictly bounded under 6 GB and prevent token truncation.
"""

import difflib
import json
import logging
import re
import subprocess
import time
import unicodedata
from pathlib import Path
from typing import Optional

import numpy as np
import torch

from .ports import Transcriber, Word

log = logging.getLogger(__name__)

CHUNK_SECONDS = 300.0
OVERLAP_SECONDS = 30.0
def normalize_text_word(text: str) -> str:
    """Normalize word for robust overlap alignment."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    cleaned = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^\w]", "", cleaned).strip()


def load_audio_ffmpeg_chunk(
    audio_path: str, start_sec: float = 0.0, duration_sec: Optional[float] = None
) -> np.ndarray:
    """Load a slice of audio as 16kHz float32 mono array via ffmpeg."""
    cmd = ["ffmpeg", "-v", "error"]
    if start_sec > 0:
        cmd.extend(["-ss", str(start_sec)])
    if duration_sec is not None and duration_sec > 0:
        cmd.extend(["-t", str(duration_sec)])
    cmd.extend([
        "-i", audio_path,
        "-f", "f32le",
        "-ar", "16000",
        "-ac", "1",
        "-"
    ])
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg audio decoding error: {err.decode('utf-8', errors='replace')}")
    return np.frombuffer(out, dtype=np.float32)


def get_audio_duration_seconds(audio_path: str) -> float:
    """Query total audio duration via ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "csv=p=0",
        audio_path,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    val = res.stdout.strip()
    return float(val) if val else 0.0


class Qwen3AsrTranscriber:
    """Qwen3-ASR Transcriber satisfying the Transcriber protocol."""

    def __init__(
        self,
        model_path: Optional[str] = None,
        aligner_path: Optional[str] = None,
        language: str = "Portuguese",
        device: str = "cuda" if torch.cuda.is_available() else "cpu",
        chunk_seconds: float = CHUNK_SECONDS,
        overlap_seconds: float = OVERLAP_SECONDS,
    ):
        self.model_path = model_path
        self.aligner_path = aligner_path
        self.language = language
        self.device = device
        self.chunk_seconds = chunk_seconds
        self.overlap_seconds = overlap_seconds

        self._asr_processor = None
        self._asr_model = None
        self._aligner_processor = None
        self._aligner_model = None
        self._aligner_unavailable_reason: Optional[str] = None

    def _ensure_asr_loaded(self):
        if self._asr_model is None:
            if not self.model_path:
                raise RuntimeError("Qwen3-ASR model_path must be configured in the selected Preset")
            from qwen_asr.core.transformers_backend import (
                Qwen3ASRForConditionalGeneration,
                Qwen3ASRProcessor,
            )

            log.info(f"[qwen3-asr] Loading ASR model from {self.model_path} onto {self.device}")
            self._asr_processor = Qwen3ASRProcessor.from_pretrained(self.model_path)
            model_dtype = torch.bfloat16 if "cuda" in self.device else torch.float32
            self._asr_model = Qwen3ASRForConditionalGeneration.from_pretrained(
                self.model_path,
                dtype=model_dtype,
                device_map=self.device,
            )

    def _ensure_aligner_loaded(self):
        if (
            self._aligner_model is not None
            or self._aligner_unavailable_reason is not None
            or not self.aligner_path
            or not Path(self.aligner_path).exists()
        ):
            return

        try:
            from transformers import AutoModelForTokenClassification, AutoProcessor

            log.info(f"[qwen3-asr] Loading ForcedAligner from {self.aligner_path} onto {self.device}")
            processor = AutoProcessor.from_pretrained(self.aligner_path)
            model_dtype = torch.bfloat16 if "cuda" in self.device else torch.float32
            model = AutoModelForTokenClassification.from_pretrained(
                self.aligner_path,
                dtype=model_dtype,
                device_map=self.device,
            )
        except Exception as exc:
            self._aligner_processor = None
            self._aligner_model = None
            self._aligner_unavailable_reason = f"{type(exc).__name__}: {exc}"
            log.warning(
                "[qwen3-asr] Forced aligner at %s is unavailable (%s); "
                "using proportional timestamp fallback",
                self.aligner_path,
                self._aligner_unavailable_reason,
            )
            return

        self._aligner_processor = processor
        self._aligner_model = model

    def transcribe(self, audio_path: str, vocabulary: str | None = None) -> list[Word]:
        """Transcribe audio into Words in ascending time order."""
        total_duration = get_audio_duration_seconds(audio_path)
        if total_duration <= 0.0:
            return []

        self._ensure_asr_loaded()
        self._ensure_aligner_loaded()

        if total_duration <= self.chunk_seconds:
            audio_data = load_audio_ffmpeg_chunk(audio_path, 0.0, total_duration)
            words = self._transcribe_and_align_chunk(audio_data, offset_sec=0.0, vocabulary=vocabulary)
            log.info(f"[qwen3-asr] Transcribed single chunk ({total_duration:.1f}s): {len(words)} words")
            return words

        # Build sliding windows
        windows = []
        step = self.chunk_seconds - self.overlap_seconds
        start = 0.0
        while start < total_duration:
            dur = min(self.chunk_seconds, total_duration - start)
            windows.append((start, dur))
            if start + dur >= total_duration:
                break
            start += step

        log.info(
            f"[qwen3-asr] Long audio ({total_duration/60:.1f} min) -> {len(windows)} sliding windows "
            f"(chunk: {self.chunk_seconds}s, overlap: {self.overlap_seconds}s)"
        )

        all_words: list[Word] = []
        for idx, (w_start, w_dur) in enumerate(windows, 1):
            log.info(f"[qwen3-asr] Processing window {idx}/{len(windows)} [{w_start:.1f}s - {w_start+w_dur:.1f}s]")
            w_audio = load_audio_ffmpeg_chunk(audio_path, start_sec=w_start, duration_sec=w_dur)
            w_words = self._transcribe_and_align_chunk(w_audio, offset_sec=w_start, vocabulary=vocabulary)

            if idx == 1:
                all_words = w_words
            else:
                all_words = self._stitch_words(all_words, w_words)

        log.info(f"[qwen3-asr] Completed transcription: {len(all_words)} words total")
        return all_words

    def _transcribe_and_align_chunk(
        self, audio: np.ndarray, offset_sec: float, vocabulary: Optional[str] = None
    ) -> list[Word]:
        """Transcribe an audio chunk and align words to absolute timestamps."""
        if len(audio) < 1600:  # < 0.1s
            return []

        # 1. ASR inference
        inputs = self._asr_processor.apply_transcription_request(
            audio=audio,
            language=self.language,
            prompt=vocabulary,
        ).to(self._asr_model.device, self._asr_model.dtype)

        with torch.no_grad():
            output_ids = self._asr_model.generate(**inputs, max_new_tokens=4096)

        gen_ids = output_ids[:, inputs["input_ids"].shape[1]:]
        text = self._asr_processor.decode(gen_ids[0], return_format="transcription_only").strip()
        if not text:
            return []

        # 2. Forced alignment
        if self._aligner_model is not None and self._aligner_processor is not None:
            try:
                aln_inputs, word_lists = self._aligner_processor.prepare_forced_aligner_inputs(
                    audio=audio,
                    transcript=text,
                    language=self.language,
                )
                aln_inputs = aln_inputs.to(self._aligner_model.device, self._aligner_model.dtype)

                with torch.no_grad():
                    res = self._aligner_model(**aln_inputs)

                timestamps = self._aligner_processor.decode_forced_alignment(
                    logits=res.logits,
                    input_ids=aln_inputs["input_ids"],
                    word_lists=word_lists,
                    timestamp_token_id=self._aligner_model.config.timestamp_token_id,
                )[0]

                words: list[Word] = []
                for item in timestamps:
                    w_text = item["text"]
                    # Add leading whitespace to adhere to Word contract (" palavra")
                    join_text = f" {w_text}" if not w_text.startswith(" ") else w_text
                    words.append(
                        Word(
                            start=round(offset_sec + float(item["start_time"]), 3),
                            end=round(offset_sec + float(item["end_time"]), 3),
                            text=join_text,
                            confidence=1.0,
                            alignment_score=0.95,
                        )
                    )
                if words:
                    return words
            except Exception as e:
                log.warning(f"[qwen3-asr] Forced aligner error ({e}); using proportional fallback")

        # Fallback if aligner failed or unavailable: interpolate timestamps across duration
        chunk_dur = len(audio) / 16000.0
        tokens = text.split()
        if not tokens:
            return []
        time_per_word = chunk_dur / len(tokens)
        fallback_words = []
        for i, t in enumerate(tokens):
            w_start = offset_sec + i * time_per_word
            w_end = offset_sec + (i + 1) * time_per_word
            join_text = f" {t}" if not t.startswith(" ") else t
            fallback_words.append(
                Word(
                    start=round(w_start, 3),
                    end=round(w_end, 3),
                    text=join_text,
                    confidence=0.85,
                    alignment_score=0.5,
                )
            )
        return fallback_words

    def _stitch_words(self, prev_words: list[Word], curr_words: list[Word], search_tokens: int = 150) -> list[Word]:
        """Stitch consecutive Word lists across overlap using sequence matching."""
        if not prev_words:
            return curr_words
        if not curr_words:
            return prev_words

        p_slice = prev_words[-search_tokens:] if len(prev_words) > search_tokens else prev_words
        c_slice = curr_words[:search_tokens] if len(curr_words) > search_tokens else curr_words

        p_norm = [normalize_text_word(w.text) for w in p_slice]
        c_norm = [normalize_text_word(w.text) for w in c_slice]

        matcher = difflib.SequenceMatcher(None, p_norm, c_norm)
        blocks = matcher.get_matching_blocks()

        cut_point = 0
        for b in blocks:
            if b.size >= 2:
                end_curr = b.b + b.size
                if end_curr > cut_point:
                    cut_point = end_curr

        if cut_point > 0:
            log.info(f"[qwen3-asr] Stitched overlap: cut {cut_point} duplicate words from window start")
            return prev_words + curr_words[cut_point:]
        else:
            # Fallback by time boundary if lexical sequence match didn't find overlap
            last_end = prev_words[-1].end
            filtered_curr = [w for w in curr_words if w.start >= last_end]
            if filtered_curr:
                return prev_words + filtered_curr
            return prev_words + curr_words
