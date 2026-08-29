"""Overlap metadata derived from Diarizer Turns."""

from .ports import Turn


def compute_overlaps(turns: list[Turn]) -> list[dict]:
    """Return intervals where two or more distinct Speakers overlap."""
    if len(turns) < 2:
        return []

    boundaries = {round(value, 3) for turn in turns for value in (turn.start, turn.end)}
    sorted_times = sorted(boundaries)
    raw_intervals: list[dict] = []
    for start, end in zip(sorted_times, sorted_times[1:]):
        if end <= start:
            continue
        speakers = {
            turn.speaker
            for turn in turns
            if round(turn.start, 3) <= start and round(turn.end, 3) >= end
        }
        if len(speakers) >= 2:
            raw_intervals.append({"start": start, "end": end, "speakers": sorted(speakers)})

    merged: list[dict] = []
    for interval in raw_intervals:
        if (
            merged
            and abs(merged[-1]["end"] - interval["start"]) < 1e-5
            and merged[-1]["speakers"] == interval["speakers"]
        ):
            merged[-1]["end"] = interval["end"]
        else:
            merged.append(dict(interval))
    return merged
