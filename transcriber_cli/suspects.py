"""Passages of a Meeting worth a second look, found without hearing the audio."""

import re

SENTENCE_END = re.compile(r"[.!?…]+")
NOT_WORD = re.compile(r"[^\w\s]|_")


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


def low_confidence_words(words: list[dict], segments: list[dict], below: float = 0.6) -> list[dict]:
    """Words under ``below``, each tagged with the order of the Segment whose time contains it."""
    found = []
    for word in words:
        confidence = word.get("confidence")
        if confidence is None or confidence >= below:
            continue
        owner = next(
            (s for s in segments if s["start_time"] <= word["start"] < s["end_time"]), None
        )
        found.append({**word, "segment_order": owner["order"] if owner else None})
    return found


def corrected_segments(segments: list[dict]) -> list[dict]:
    """Segments where Vocabulary Correction replaced a heard form."""
    return [s for s in segments if s.get("corrections")]
