"""Splits long audio into pieces cut where it is quietest nearby.

Shared by any Transcriber whose single-call cost — VRAM, wall-clock time, or
both — does not scale to a full meeting. A cut lands wherever the audio is
quietest near the target, so it falls in a pause rather than through the
middle of a word.
"""

import numpy as np

SNAP_SECONDS = 15
QUIET_WINDOW_SECONDS = 0.5


def chunk_bounds(
    audio: np.ndarray, sample_rate: int, chunk_seconds: float, min_tail_seconds: float
) -> list[tuple[float, float]]:
    """(start, end) pairs in seconds covering the audio, cut where it is quietest."""
    duration = len(audio) / sample_rate
    bounds = []
    start = 0.0
    while duration - start > chunk_seconds:
        cut = _quietest_point(audio, sample_rate, start + chunk_seconds)
        if duration - cut < min_tail_seconds:
            break
        bounds.append((start, cut))
        start = cut
    bounds.append((start, duration))
    return bounds


def _quietest_point(audio: np.ndarray, sample_rate: int, target: float) -> float:
    """The centre of the quietest short window within SNAP_SECONDS of `target`.

    A boundary in a pause costs nothing; a boundary through a word costs that word,
    because neither chunk sees enough of it to recognise it.
    """
    lo = max(0, int((target - SNAP_SECONDS) * sample_rate))
    hi = min(len(audio), int((target + SNAP_SECONDS) * sample_rate))
    window = int(QUIET_WINDOW_SECONDS * sample_rate)
    if hi - lo <= window:
        return target

    # Energy of every window in [lo, hi), via a rolling sum of squares.
    squares = np.concatenate(([0.0], np.cumsum(np.square(audio[lo:hi], dtype=np.float64))))
    energy = squares[window:] - squares[:-window]
    quietest = int(np.argmin(energy))

    return (lo + quietest + window / 2) / sample_rate
