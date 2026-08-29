"""Overlap metadata derived from Diarizer Turns."""

from .ports import Turn


def compute_overlaps(turns: list[Turn]) -> list[dict]:
    """Return intervals where two or more distinct Speakers overlap."""
    if len(turns) < 2:
        return []

    events: dict[float, list[tuple[int, str]]] = {}
    for turn in turns:
        start = round(turn.start, 3)
        end = round(turn.end, 3)
        if end <= start:
            continue
        events.setdefault(start, []).append((1, turn.speaker))
        events.setdefault(end, []).append((-1, turn.speaker))

    sorted_times = sorted(events)
    active: dict[str, int] = {}
    raw_intervals: list[dict] = []
    for start, end in zip(sorted_times, sorted_times[1:]):
        for delta, speaker in events[start]:
            count = active.get(speaker, 0) + delta
            if count:
                active[speaker] = count
            else:
                active.pop(speaker, None)
        if end <= start:
            continue
        if len(active) >= 2:
            raw_intervals.append({"start": start, "end": end, "speakers": sorted(active)})

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
