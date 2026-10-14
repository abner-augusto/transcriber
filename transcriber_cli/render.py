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
        mark = "confirmed" if fix.get("confirmed") else "fixed"
        line += f" [{mark}: {fix['heard'].strip()}->{fix['term'].strip()}]"
    return line


NOTE_TOLERANCE = 1.5  # the app's EDIT_TIME_TOLERANCE: how far a Segment may sit from a note's range


def note_segment(note: dict, segments: list[dict]) -> dict | None:
    """The Segment the app would pick for the note's range now, or None."""
    near = [
        (abs(s["start_time"] - note["start_time"]) + abs(s["end_time"] - note["end_time"]), s)
        for s in segments
        if abs(s["start_time"] - note["start_time"]) < NOTE_TOLERANCE
        and abs(s["end_time"] - note["end_time"]) < NOTE_TOLERANCE
    ]
    return min(near, key=lambda pair: pair[0])[1] if near else None


def _proposal(note: dict) -> str | None:
    payload = note.get("payload") or {}
    if note["kind"] == "text":
        return payload.get("proposed_text")
    if note["kind"] == "speaker_name":
        return payload.get("name")
    if note["kind"] == "speaker_move":
        return payload.get("target_label") or f"new:{payload.get('new_name')}"
    if note["kind"] == "speaker_merge":
        return f"{payload.get('source_label')} into {payload.get('target_label')}"
    if note["kind"] == "split":
        target = payload.get("target_label") or (f"new:{payload['new_name']}" if payload.get("new_name") else None)
        return f"before \"{payload.get('preview')}\"" + (f" to {target}" if target else "")
    return None


def note_line(note: dict, segments: list[dict]) -> str:
    segment = note_segment(note, segments)
    anchor = f"#{segment['order']}" if segment else "#?"
    line = (
        f"n:{note['id'][:8]} {anchor} {clock(note['start_time'])} "
        f"{note['kind']}/{note['status']} {note['author']}: {note['body']}"
    )
    proposal = _proposal(note)
    if proposal is not None:
        line += f" -> {proposal}"
    if note.get("answer"):
        line += f" answer: {note['answer']}"
    if note.get("reply"):
        line += f" reply: {note['reply']}"
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
    lines = [f"{name}: {value}" for name, value in rows if value]
    for source in m.get("sources") or []:
        where = source["path"] or "path not saved"
        lines.append(f"source {source['track']}: {source['name']} ({source['state']}) {where}")
    return lines


def word_line(word: dict) -> str:
    confidence = word.get("confidence")
    shown = "-" if confidence is None else f"{confidence:.2f}"
    return f"{clock(word['start'])} {word['text'].strip()} {shown}"
