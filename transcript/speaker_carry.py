"""Which new Speaker label inherits a name the user gave an old one, after new Turns."""

Interval = tuple[float, float]


def _total(intervals: list[Interval]) -> float:
    return sum(end - start for start, end in intervals)


def _shared(a: list[Interval], b: list[Interval]) -> float:
    return sum(
        max(0.0, min(a_end, b_end) - max(a_start, b_start))
        for a_start, a_end in a
        for b_start, b_end in b
    )


def _best(label_times: dict[str, float]) -> str | None:
    """The label with the most shared time; the alphabetically first wins a tie."""
    if not label_times:
        return None
    return min(label_times, key=lambda label: (-label_times[label], label))


def match_by_overlap(
    old: dict[str, list[Interval]],
    new: dict[str, list[Interval]],
    *, min_share: float = 0.5,
) -> dict[str, str]:
    """Map old label -> new label for mutual best matches sharing >= min_share of the old label's time."""
    shared = {
        (old_label, new_label): _shared(old_intervals, new_intervals)
        for old_label, old_intervals in old.items()
        for new_label, new_intervals in new.items()
    }
    matches = {}
    for old_label, old_intervals in sorted(old.items()):
        spoken = _total(old_intervals)
        if spoken <= 0:
            continue
        best_new = _best({n: shared[old_label, n] for n in new if shared[old_label, n] > 0})
        if best_new is None:
            continue
        best_old = _best({o: shared[o, best_new] for o in old if shared[o, best_new] > 0})
        if best_old == old_label and shared[old_label, best_new] >= min_share * spoken:
            matches[old_label] = best_new
    return matches
