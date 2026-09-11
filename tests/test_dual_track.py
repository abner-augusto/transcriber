"""Dual-track diarization: deterministic host attribution + neural remote diarization.

These tests cover the turn combination, crosstalk preservation, exclusive-turn
computation, and the host/remote split that make dual-track Meetings work.
"""

from engines import Turn, DiarizationResult, compute_overlaps
from tasks.dual_track import (
    HOST_SPEAKER,
    build_dual_diarization,
    compute_exclusive_turns,
    host_turns_from_vad,
    merge_dual_turns,
)


def test_host_turns_from_vad_attributes_every_region_to_host():
    vad_segments = [(0.0, 1.5), (3.0, 5.0), (7.0, 8.0)]
    turns = host_turns_from_vad(vad_segments)

    assert len(turns) == 3
    assert all(t.speaker == HOST_SPEAKER for t in turns)
    assert turns[0] == Turn(start=0.0, end=1.5, speaker=HOST_SPEAKER)
    assert turns[1] == Turn(start=3.0, end=5.0, speaker=HOST_SPEAKER)
    assert turns[2] == Turn(start=7.0, end=8.0, speaker=HOST_SPEAKER)


def test_host_turns_from_vad_drops_empty_regions():
    vad_segments = [(0.0, 0.0), (1.0, 2.0)]
    turns = host_turns_from_vad(vad_segments)

    assert len(turns) == 1
    assert turns[0] == Turn(start=1.0, end=2.0, speaker=HOST_SPEAKER)


def test_host_turns_from_vad_empty_input():
    assert host_turns_from_vad([]) == []


def test_merge_combines_host_and_remote_turns_sorted_by_start():
    host = [Turn(start=2.0, end=4.0, speaker=HOST_SPEAKER)]
    remote = [
        Turn(start=0.0, end=1.0, speaker="SPEAKER_00"),
        Turn(start=5.0, end=6.0, speaker="SPEAKER_01"),
    ]

    merged = merge_dual_turns(host, remote)

    assert [t.speaker for t in merged] == ["SPEAKER_00", HOST_SPEAKER, "SPEAKER_01"]
    assert merged[0].start == 0.0
    assert merged[1].start == 2.0
    assert merged[2].start == 5.0


def test_merge_preserves_crosstalk_overlaps():
    """When host and remote talk simultaneously, both Turns are kept."""
    host = [Turn(start=2.0, end=5.0, speaker=HOST_SPEAKER)]
    remote = [Turn(start=3.0, end=6.0, speaker="SPEAKER_00")]

    merged = merge_dual_turns(host, remote)

    assert len(merged) == 2
    # Both turns survive the overlap.
    assert Turn(start=2.0, end=5.0, speaker=HOST_SPEAKER) in merged
    assert Turn(start=3.0, end=6.0, speaker="SPEAKER_00") in merged

    # The overlap region is detected.
    overlaps = compute_overlaps(merged)
    assert overlaps == [
        {"start": 3.0, "end": 5.0, "speakers": [HOST_SPEAKER, "SPEAKER_00"]},
    ]


def test_merge_empty_host_keeps_remote_only():
    remote = [Turn(start=0.0, end=2.0, speaker="SPEAKER_00")]
    merged = merge_dual_turns([], remote)

    assert merged == remote


def test_merge_empty_remote_keeps_host_only():
    host = [Turn(start=0.0, end=2.0, speaker=HOST_SPEAKER)]
    merged = merge_dual_turns(host, [])

    assert merged == host


def test_compute_exclusive_turns_splits_overlapping_portions():
    """Each Turn keeps only the region where no other speaker is active."""
    turns = [
        Turn(start=0.0, end=5.0, speaker=HOST_SPEAKER),
        Turn(start=3.0, end=8.0, speaker="SPEAKER_00"),
    ]

    exclusive = compute_exclusive_turns(turns)

    # Host: [0,3] (the [3,5] overlap is dropped).
    # Remote: [5,8] (the [3,5] overlap is dropped).
    assert exclusive == [
        Turn(start=0.0, end=3.0, speaker=HOST_SPEAKER),
        Turn(start=5.0, end=8.0, speaker="SPEAKER_00"),
    ]


def test_compute_exclusive_turns_keeps_disjoint_turns_whole():
    turns = [
        Turn(start=0.0, end=2.0, speaker=HOST_SPEAKER),
        Turn(start=3.0, end=5.0, speaker="SPEAKER_00"),
    ]

    exclusive = compute_exclusive_turns(turns)

    assert exclusive == turns


def test_compute_exclusive_turns_three_speakers():
    turns = [
        Turn(start=0.0, end=5.0, speaker=HOST_SPEAKER),
        Turn(start=2.0, end=4.0, speaker="SPEAKER_00"),
        Turn(start=3.0, end=6.0, speaker="SPEAKER_01"),
    ]

    exclusive = compute_exclusive_turns(turns)

    # Host [0,5]: overlapped by SPEAKER_00 [2,4] and SPEAKER_01 [3,6] -> union [2,5],
    # so exclusive = [0,2].
    # SPEAKER_00 [2,4]: fully covered by Host [0,5] -> no exclusive portion.
    # SPEAKER_01 [3,6]: overlapped by Host [0,5] -> exclusive = [5,6].
    by_speaker = {}
    for t in exclusive:
        by_speaker.setdefault(t.speaker, []).append(t)

    assert by_speaker[HOST_SPEAKER] == [Turn(start=0.0, end=2.0, speaker=HOST_SPEAKER)]
    assert by_speaker.get("SPEAKER_00", []) == []
    assert by_speaker["SPEAKER_01"] == [Turn(start=5.0, end=6.0, speaker="SPEAKER_01")]


def test_compute_exclusive_turns_empty():
    assert compute_exclusive_turns([]) == []


def test_build_dual_diarization_assembles_full_result():
    host = [Turn(start=0.0, end=2.0, speaker=HOST_SPEAKER)]
    remote = [Turn(start=1.0, end=4.0, speaker="SPEAKER_00")]

    result = build_dual_diarization(host, remote)

    assert isinstance(result, DiarizationResult)
    assert result.turns == [
        Turn(start=0.0, end=2.0, speaker=HOST_SPEAKER),
        Turn(start=1.0, end=4.0, speaker="SPEAKER_00"),
    ]
    assert result.exclusive_turns == [
        Turn(start=0.0, end=1.0, speaker=HOST_SPEAKER),
        Turn(start=2.0, end=4.0, speaker="SPEAKER_00"),
    ]
    assert result.overlaps == [
        {"start": 1.0, "end": 2.0, "speakers": [HOST_SPEAKER, "SPEAKER_00"]},
    ]


def test_build_dual_diarization_accepts_supplied_exclusive_turns():
    host = [Turn(start=0.0, end=2.0, speaker=HOST_SPEAKER)]
    remote = [Turn(start=1.0, end=4.0, speaker="SPEAKER_00")]
    supplied = [Turn(start=0.0, end=1.0, speaker=HOST_SPEAKER)]

    result = build_dual_diarization(host, remote, exclusive_turns=supplied)

    assert result.exclusive_turns == supplied


def test_single_file_fallback_is_not_dual_track():
    """A single-track Meeting has no host/remote split — the host label is absent."""
    # Simulate the single-track path: only remote-style turns, no host.
    turns = [Turn(start=0.0, end=2.0, speaker="SPEAKER_00")]
    exclusive = compute_exclusive_turns(turns)

    assert exclusive == turns
    # No HOST_SPEAKER present.
    assert all(t.speaker != HOST_SPEAKER for t in turns)
