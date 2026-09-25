"""Dual-track diarization: deterministic host attribution + neural remote diarization.

A dual-track Meeting carries two sources: the local microphone (mic) and the remote
meeting / desktop audio (system). The local speaker is attributed deterministically —
every speech region on the mic track belongs to the host, with no neural clustering.
The remote speakers are isolated by running the Diarizer exclusively on the system
track, which removes the local mic signal and prevents cross-speaker confusion.

The two turn sets are merged into one unified DiarizationResult. Because both tracks
are the same recording, their timelines align, and overlapping (crosstalk) regions
are preserved rather than collapsed.
"""

from engines import Turn, DiarizationResult, compute_overlaps, compute_exclusive_turns

# The Diarizer-local label for the host (local mic) speaker. Naming is the Speaker
# Namer's job; this is the label that gets named "You".
HOST_SPEAKER = "HOST"


def host_turns_from_vad(vad_segments: list[tuple[float, float]]) -> list[Turn]:
    """Deterministic host Turns from VAD speech regions on the mic track.

    Every speech region on the mic track is attributed to the host with 100%
    confidence — no neural clustering. Each VAD region becomes one host Turn.
    """
    return [
        Turn(start=round(s, 3), end=round(e, 3), speaker=HOST_SPEAKER)
        for s, e in vad_segments
        if e > s
    ]


def merge_dual_turns(host_turns: list[Turn], remote_turns: list[Turn]) -> list[Turn]:
    """Combine host and remote Turns into one unified set.

    Overlaps (crosstalk) are preserved: when the host and a remote speaker talk
    simultaneously, both Turns are kept. The result is sorted by start time.
    """
    merged = list(host_turns) + list(remote_turns)
    merged.sort(key=lambda t: (t.start, t.end, t.speaker))
    return merged


def build_dual_diarization(
    host_turns: list[Turn],
    remote_turns: list[Turn],
    exclusive_turns: list[Turn] | None = None,
) -> DiarizationResult:
    """Assemble the unified DiarizationResult for a dual-track Meeting.

    ``exclusive_turns`` defaults to the computed exclusive portions of the merged
    Turns when not supplied.
    """
    merged = merge_dual_turns(host_turns, remote_turns)
    if exclusive_turns is None:
        exclusive_turns = compute_exclusive_turns(merged)
    overlaps = compute_overlaps(merged)
    return DiarizationResult(
        turns=merged,
        exclusive_turns=exclusive_turns,
        overlaps=overlaps,
    )
