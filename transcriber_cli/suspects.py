"""Passages of a Meeting worth a second look, found without hearing the audio."""

import re

SENTENCE_END = re.compile(r"[.!?…]+")
NOT_WORD = re.compile(r"[^\w\s]|_")
# Word confidence. Segment confidence (0.6, render.LOW_CONFIDENCE) is a different scale.
WEAK_WORD = 0.4


def _sentences(text: str) -> list[str]:
    """Casefolded sentences with only letters, digits and single spaces."""
    found = []
    for part in SENTENCE_END.split(text or ""):
        normal = " ".join(NOT_WORD.sub("", part.casefold()).split())
        if normal:
            found.append(normal)
    return found


def repetition_windows(segments: list[dict], min_run: int = 3) -> list[dict]:
    """Runs of the same sentence repeated back to back: the signature of a
    Transcriber filling silence. Returns {start, end, first_order, last_order, text, count}."""
    flat = [(sentence, seg) for seg in segments for sentence in _sentences(seg["text"])]
    windows = []
    index = 0
    while index < len(flat):
        end = index
        while end + 1 < len(flat) and flat[end + 1][0] == flat[index][0]:
            end += 1
        count = end - index + 1
        if count >= min_run:
            first, last = flat[index][1], flat[end][1]
            windows.append({
                "start": first["start_time"],
                "end": last["end_time"],
                "first_order": first["order"],
                "last_order": last["order"],
                "text": flat[index][0],
                "count": count,
            })
        index = end + 1
    return windows


def low_confidence_passages(
    words: list[dict], segments: list[dict], below: float = WEAK_WORD
) -> list[dict]:
    """Segments holding at least one Word under ``below``, worst Word first.
    Returns {order, worst, words: [(text, confidence), ...]} sorted by worst ascending;
    the weak Words of a Segment stay in time order. An edited Segment is skipped: its
    Words describe the text the edit replaced."""
    weak: dict[int, list[tuple[str, float]]] = {}
    for word in sorted(words, key=lambda w: w["start"]):
        confidence = word.get("confidence")
        if confidence is None or confidence >= below:
            continue
        owner = next(
            (s for s in segments if s["start_time"] <= word["start"] < s["end_time"]), None
        )
        if owner is not None and not owner.get("is_edited"):
            weak.setdefault(owner["order"], []).append((word["text"], confidence))
    passages = [
        {"order": order, "worst": min(c for _, c in found), "words": found}
        for order, found in weak.items()
    ]
    return sorted(passages, key=lambda p: p["worst"])


def corrected_segments(segments: list[dict]) -> list[dict]:
    """Segments where Vocabulary Correction replaced a heard form."""
    return [s for s in segments if s.get("corrections")]
