"""Compact plain-ASCII text for Meetings, Segments, and Speakers."""

LOW_CONFIDENCE = 0.6  # TranscriptView.tsx draws a Segment below this as low-confidence


def clock(seconds: float) -> str:
    """`MM:SS`, or `H:MM:SS` from one hour."""
    total = int(seconds or 0)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def parse_clock(text: str) -> float:
    """Seconds from `SS`, `MM:SS`, `H:MM:SS`, or plain (decimal) seconds."""
    parts = text.strip().split(":")
    if not 1 <= len(parts) <= 3:
        raise ValueError(f"not a time: '{text}'")
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + float(part)
    return seconds


def segment_line(seg: dict) -> str:
    who = seg.get("speaker_name") or seg.get("speaker_label") or "?"
    line = f"#{seg['order']} {clock(seg['start_time'])} {who}: {seg['text']}"
    if seg.get("is_edited"):
        line += " [edited]"
    if seg.get("speaker_edited"):
        line += " [moved]"
    confidence = seg.get("confidence")
    if confidence is not None and confidence < LOW_CONFIDENCE:
        line += f" [conf {confidence:.2f}]"
    for fix in seg.get("corrections") or []:
        line += f" [fixed: {fix['heard'].strip()}->{fix['term'].strip()}]"
    return line


def speaker_line(sp: dict) -> str:
    return (
        f'{sp["label"]} "{sp.get("display_name") or ""}" '
        f'by={sp.get("identified_by") or "-"} '
        f'segs={sp.get("segment_count") or 0} '
        f'time={clock(sp.get("total_speaking_time") or 0)}'
    )


def meeting_header(m: dict) -> list[str]:
    rows = [
        ("id", m.get("id")),
        ("title", m.get("title")),
        ("status", m.get("status")),
        ("duration", clock(m["duration"]) if m.get("duration") else None),
        ("participants", m.get("participants")),
        ("vocabulary", m.get("vocabulary")),
    ]
    return [f"{name}: {value}" for name, value in rows if value]


def word_line(word: dict) -> str:
    confidence = word.get("confidence")
    shown = "-" if confidence is None else f"{confidence:.2f}"
    return f"{clock(word['start'])} {word['text'].strip()} {shown}"
