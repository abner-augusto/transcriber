"""Tests for VadService and mask_turns_to_vad."""

import numpy as np
import pytest

from engines import Turn, Word
from services.vad_service import VadService, mask_turns_to_vad, merge_intervals
from tasks.shared import build_segments


def spoken(text: str, start: float, end: float, confidence: float | None = None) -> Word:
    return Word(
        start=start,
        end=end,
        text=text if text.startswith(" ") else " " + text,
        confidence=confidence,
    )


def test_normal_speech_turn_within_vad_bounds():
    """A Turn completely inside speech bounds remains unchanged."""
    turns = [Turn(start=1.0, end=4.0, speaker="SPEAKER_00")]
    vad_segments = [(0.5, 5.0)]

    masked = mask_turns_to_vad(turns, vad_segments)

    assert len(masked) == 1
    assert masked[0] == Turn(start=1.0, end=4.0, speaker="SPEAKER_00")


def test_clipping_turn_extending_past_vad_bounds():
    """A Turn extending before or after speech bounds is clipped."""
    turns = [
        Turn(start=0.5, end=6.0, speaker="SPEAKER_00"),
    ]
    vad_segments = [(1.0, 5.0)]

    masked = mask_turns_to_vad(turns, vad_segments)

    assert len(masked) == 1
    assert masked[0] == Turn(start=1.0, end=5.0, speaker="SPEAKER_00")


def test_discarded_non_speech_turn():
    """Turns occurring entirely in non-speech regions are discarded."""
    turns = [
        Turn(start=0.0, end=3.0, speaker="SPEAKER_00"),  # inside speech
        Turn(start=5.0, end=8.0, speaker="SPEAKER_01"),  # hallucination in silence
    ]
    vad_segments = [(0.0, 3.0)]

    masked = mask_turns_to_vad(turns, vad_segments)

    assert len(masked) == 1
    assert masked[0] == Turn(start=0.0, end=3.0, speaker="SPEAKER_00")


def test_turn_split_across_multiple_speech_regions():
    """A Turn spanning across a long silence gap is split into two clipped Turns."""
    turns = [
        Turn(start=1.0, end=10.0, speaker="SPEAKER_00"),
    ]
    # Two speech regions separated by 2 seconds of silence
    vad_segments = [(1.5, 4.0), (6.0, 9.5)]

    masked = mask_turns_to_vad(turns, vad_segments)

    assert len(masked) == 2
    assert masked[0] == Turn(start=1.5, end=4.0, speaker="SPEAKER_00")
    assert masked[1] == Turn(start=6.0, end=9.5, speaker="SPEAKER_00")


def test_short_gaps_merged_without_splitting():
    """Short gaps between adjacent speech regions (<= merge_gap_seconds) are merged."""
    turns = [
        Turn(start=1.0, end=5.0, speaker="SPEAKER_00"),
    ]
    # Two speech regions separated by 0.1s (< default merge_gap 0.3s)
    vad_segments = [(1.0, 2.5), (2.6, 5.0)]

    masked = mask_turns_to_vad(turns, vad_segments, merge_gap_seconds=0.3)

    assert len(masked) == 1
    assert masked[0] == Turn(start=1.0, end=5.0, speaker="SPEAKER_00")


def test_empty_vad_output():
    """When VAD detects no speech, all turns are discarded."""
    turns = [
        Turn(start=0.0, end=5.0, speaker="SPEAKER_00"),
    ]
    vad_segments = []

    masked = mask_turns_to_vad(turns, vad_segments)

    assert masked == []


def test_empty_turns_input():
    """When input turns list is empty, returns empty list."""
    vad_segments = [(0.0, 5.0)]
    assert mask_turns_to_vad([], vad_segments) == []


def test_boundary_adjacent_words_attribution():
    """Words near or slightly extending past clipped Turn boundaries are attributed properly."""
    turns = [Turn(start=0.0, end=5.0, speaker="SPEAKER_00")]
    # VAD clips turn to [1.0, 4.0]
    vad_segments = [(1.0, 4.0)]
    bounded_turns = mask_turns_to_vad(turns, vad_segments)

    # Word crossing start boundary [0.9, 1.3] (overlaps bounded turn [1.0, 4.0])
    word_start_boundary = spoken("hello", 0.9, 1.3)
    # Word crossing end boundary [3.8, 4.1] (overlaps bounded turn [1.0, 4.0])
    word_end_boundary = spoken("there", 1.3, 1.7)
    # Word just outside end boundary [4.05, 4.2] (within nearest tolerance)
    word_near = spoken("friend", 4.05, 4.2)

    segments = build_segments([word_start_boundary, word_end_boundary], bounded_turns)
    assert len(segments) == 1
    assert segments[0]["speaker"] == "SPEAKER_00"
    assert segments[0]["text"] == "hello there"

    # Verify nearest attribution for word slightly beyond clipped turn
    segments_near = build_segments([word_near], bounded_turns)
    assert len(segments_near) == 1
    assert segments_near[0]["speaker"] == "SPEAKER_00"
    assert segments_near[0]["text"] == "friend"


def test_vad_service_compute_vad_segments_empty_audio():
    """compute_vad_segments handles empty audio array gracefully."""
    service = VadService()
    res = service.compute_vad_segments(np.array([], dtype=np.float32))
    assert res == []


def test_vad_service_mask_turns_to_vad_method():
    """VadService.mask_turns_to_vad method operates consistently."""
    service = VadService(merge_gap_seconds=0.2)
    turns = [
        Turn(start=0.0, end=10.0, speaker="SPEAKER_00"),
    ]
    vad_segments = [{"start": 1.0, "end": 4.0}, {"start": 4.1, "end": 8.0}]

    masked = service.mask_turns_to_vad(turns, vad_segments)

    # 4.0 to 4.1 is 0.1s gap <= 0.2s merge_gap -> merged to [1.0, 8.0]
    assert len(masked) == 1
    assert masked[0] == Turn(start=1.0, end=8.0, speaker="SPEAKER_00")


def test_merge_intervals_helper():
    assert merge_intervals([]) == []
    assert merge_intervals([(1.0, 2.0)]) == [(1.0, 2.0)]
    # Overlapping intervals
    assert merge_intervals([(1.0, 3.0), (2.0, 4.0)]) == [(1.0, 4.0)]
    # Disjoint intervals beyond merge gap
    assert merge_intervals([(1.0, 2.0), (3.0, 4.0)], merge_gap_seconds=0.5) == [
        (1.0, 2.0),
        (3.0, 4.0),
    ]
    # Intervals within merge gap
    assert merge_intervals([(1.0, 2.0), (2.3, 4.0)], merge_gap_seconds=0.5) == [
        (1.0, 4.0),
    ]
