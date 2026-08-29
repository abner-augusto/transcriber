"""Speech Voice Activity Detection (VAD) service.

Uses Silero VAD (via ONNX runtime through faster_whisper.vad) to detect speech bounds
in 16kHz audio. Constrains diarization Turns to valid speech regions to eliminate boundary
hallucinations and phantom turns caused by mismatches between ASR and diarizer VAD.

Model & Configuration Requirements:
- Model: Silero VAD (ONNX model bundled with faster-whisper, ~2MB).
- Audio requirement: 16kHz mono float32 audio.
- Hyperparameters:
  - threshold: 0.5 (speech probability cutoff).
  - min_speech_duration_ms: 250 (minimum duration for a speech segment).
  - min_silence_duration_ms: 100 (minimum silence to trigger segment boundary).
  - speech_pad_ms: 300 (padding around detected speech onsets and offsets).
  - merge_gap_seconds: 0.3s (maximum gap between adjacent speech regions to merge them).

Resource Impact:
- CPU/GPU memory: < 50MB RAM / VRAM footprint.
- Latency: < 0.5s for 1 hour of audio (fast vectorized ONNX inference).
- Offline / Local: Zero external API calls, runs 100% locally.
"""

import logging
from pathlib import Path
from typing import Sequence, Union
import numpy as np
import soundfile as sf

from engines import Turn

log = logging.getLogger(__name__)

TARGET_SAMPLE_RATE = 16000
DEFAULT_MERGE_GAP_SECONDS = 0.3


def merge_intervals(
    intervals: Sequence[tuple[float, float]],
    merge_gap_seconds: float = DEFAULT_MERGE_GAP_SECONDS,
) -> list[tuple[float, float]]:
    """Merge overlapping or near-adjacent intervals within merge_gap_seconds."""
    if not intervals:
        return []

    # Sort intervals by start time, then end time
    sorted_intervals = sorted(intervals, key=lambda x: (x[0], x[1]))
    merged: list[tuple[float, float]] = []
    cur_start, cur_end = sorted_intervals[0]

    for start, end in sorted_intervals[1:]:
        if start <= cur_end + merge_gap_seconds:
            # Overlapping or within merge gap
            cur_end = max(cur_end, end)
        else:
            merged.append((round(cur_start, 3), round(cur_end, 3)))
            cur_start, cur_end = start, end

    merged.append((round(cur_start, 3), round(cur_end, 3)))
    return merged


def mask_turns_to_vad(
    turns: Sequence[Turn],
    vad_segments: Sequence[Union[tuple[float, float], dict]],
    merge_gap_seconds: float = DEFAULT_MERGE_GAP_SECONDS,
    min_turn_duration: float = 0.01,
) -> list[Turn]:
    """Constrain diarization Turns to regions containing speech (VAD bounds).

    Each diarization Turn is clipped to the speech bounds it overlaps. If a Turn does
    not overlap any speech region, it is discarded. If a Turn spans across multiple
    disconnected speech regions, it is split into corresponding clipped Turns with the
    same speaker label. Short gaps between adjacent speech regions are merged using
    merge_gap_seconds to avoid fragmenting turns over small intra-sentence pauses.

    Args:
        turns: List of Turn objects produced by Diarizer.
        vad_segments: List of (start, end) tuples or {"start": ..., "end": ...} dicts in seconds.
        merge_gap_seconds: Max silence gap (in seconds) between speech bounds to merge.
        min_turn_duration: Minimum duration of a clipped Turn to retain.

    Returns:
        List of clipped Turn objects in ascending time order.
    """
    if not turns or not vad_segments:
        return []

    # Convert vad_segments to list of (start, end) tuples
    norm_intervals: list[tuple[float, float]] = []
    for item in vad_segments:
        if isinstance(item, dict):
            s, e = float(item["start"]), float(item["end"])
        else:
            s, e = float(item[0]), float(item[1])
        if e > s:
            norm_intervals.append((s, e))

    if not norm_intervals:
        return []

    merged_vad = merge_intervals(norm_intervals, merge_gap_seconds=merge_gap_seconds)

    clipped_turns: list[Turn] = []
    for turn in turns:
        for v_start, v_end in merged_vad:
            c_start = max(turn.start, v_start)
            c_end = min(turn.end, v_end)
            if c_end - c_start >= min_turn_duration:
                clipped_turns.append(
                    Turn(
                        start=round(c_start, 3),
                        end=round(c_end, 3),
                        speaker=turn.speaker,
                    )
                )

    # Sort turns by start time, then end time, then speaker
    clipped_turns.sort(key=lambda t: (t.start, t.end, t.speaker))
    return clipped_turns


class VadService:
    """Service for computing speech activity bounds and masking turns."""

    def __init__(
        self,
        threshold: float = 0.5,
        min_speech_duration_ms: int = 250,
        min_silence_duration_ms: int = 100,
        speech_pad_ms: int = 300,
        merge_gap_seconds: float = DEFAULT_MERGE_GAP_SECONDS,
    ):
        self.threshold = threshold
        self.min_speech_duration_ms = min_speech_duration_ms
        self.min_silence_duration_ms = min_silence_duration_ms
        self.speech_pad_ms = speech_pad_ms
        self.merge_gap_seconds = merge_gap_seconds

    def compute_vad_segments(
        self,
        audio_input: Union[str, Path, np.ndarray],
    ) -> list[tuple[float, float]]:
        """Compute speech bounds (in seconds) from audio file or array using Silero VAD."""
        try:
            if isinstance(audio_input, (str, Path)):
                audio_path = str(audio_input)
                data, sr = sf.read(audio_path, dtype="float32", always_2d=False)
                if data.ndim > 1:
                    data = data.mean(axis=1)
                if sr != TARGET_SAMPLE_RATE:
                    import torch
                    import torchaudio.functional as F

                    tensor = torch.from_numpy(data).unsqueeze(0)
                    resampled = F.resample(tensor, sr, TARGET_SAMPLE_RATE)
                    data = resampled.squeeze(0).numpy()
            else:
                data = audio_input.astype(np.float32)
                if data.ndim > 1:
                    data = data.mean(axis=1)

            if len(data) == 0:
                return []

            from faster_whisper.vad import VadOptions, get_speech_timestamps

            options = VadOptions(
                threshold=self.threshold,
                min_speech_duration_ms=self.min_speech_duration_ms,
                min_silence_duration_ms=self.min_silence_duration_ms,
                speech_pad_ms=self.speech_pad_ms,
            )

            raw_timestamps = get_speech_timestamps(
                data,
                vad_options=options,
                sampling_rate=TARGET_SAMPLE_RATE,
            )

            intervals = [
                (
                    round(item["start"] / TARGET_SAMPLE_RATE, 3),
                    round(item["end"] / TARGET_SAMPLE_RATE, 3),
                )
                for item in raw_timestamps
                if item["end"] > item["start"]
            ]

            return merge_intervals(intervals, merge_gap_seconds=self.merge_gap_seconds)

        except Exception as e:
            log.warning(f"[vad_service] VAD extraction failed ({e})", exc_info=True)
            return []

    def mask_turns_to_vad(
        self,
        turns: Sequence[Turn],
        vad_segments: Sequence[Union[tuple[float, float], dict]],
    ) -> list[Turn]:
        """Convenience method delegating to mask_turns_to_vad function."""
        return mask_turns_to_vad(
            turns=turns,
            vad_segments=vad_segments,
            merge_gap_seconds=self.merge_gap_seconds,
        )
