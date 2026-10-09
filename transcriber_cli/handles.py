"""Short handles for Meetings, Segments, and Speakers."""

from .client import Api, ApiError

MIN_PREFIX = 4


def _ambiguous(handle, kind, candidates):
    return ApiError(400, f"'{handle}' matches {len(candidates)} {kind}: {', '.join(candidates)}")


def resolve_meeting(api: Api, handle: str) -> dict:
    """The Meeting dict for an id, a unique id prefix (4+ chars), or an exact title."""
    meetings = api.get("/api/meetings")
    for meeting in meetings:
        if meeting["id"] == handle:
            return meeting
    matches = []
    if len(handle) >= MIN_PREFIX:
        matches = [m for m in meetings if m["id"].startswith(handle)]
    if not matches:
        matches = [m for m in meetings if (m.get("title") or "").lower() == handle.lower()]
    if not matches:
        raise ApiError(404, f"No Meeting matches '{handle}'")
    if len(matches) > 1:
        names = [f"{m['id'][:8]} {m.get('title') or ''}".strip() for m in matches]
        raise _ambiguous(handle, "Meetings", names)
    return matches[0]


def resolve_segment(meeting: dict, handle: str) -> dict:
    """The Segment whose `order` is `#12` or `12`."""
    text = handle.lstrip("#")
    if not text.isdigit():
        raise ApiError(400, f"'{handle}' is not a Segment handle; use #<order>, e.g. #12")
    order = int(text)
    for segment in meeting["segments"]:
        if segment["order"] == order:
            return segment
    raise ApiError(404, f"No Segment #{order} in this Meeting")


def resolve_note(meeting: dict, handle: str) -> dict:
    """The Review Note for a full id or a unique id prefix (4+ chars); `n:` as printed is accepted."""
    text = handle[2:] if handle.startswith("n:") else handle
    notes = meeting["review_notes"]
    for note in notes:
        if note["id"] == text:
            return note
    matches = [n for n in notes if len(text) >= MIN_PREFIX and n["id"].startswith(text)]
    if not matches:
        raise ApiError(404, f"No Note matches '{handle}'")
    if len(matches) > 1:
        raise _ambiguous(handle, "Notes", [f"n:{n['id'][:8]}" for n in matches])
    return matches[0]


def resolve_speaker(meeting: dict, handle: str) -> dict:
    """The Speaker for an exact label, a display name (any case), or a unique id prefix."""
    speakers = meeting["speakers"]
    for speaker in speakers:
        if speaker["label"] == handle:
            return speaker
    matches = [s for s in speakers if (s.get("display_name") or "").lower() == handle.lower()]
    if not matches and len(handle) >= MIN_PREFIX:
        matches = [s for s in speakers if s["id"].startswith(handle)]
    if not matches:
        raise ApiError(404, f"No Speaker matches '{handle}'")
    if len(matches) > 1:
        names = [f"{s['label']} ({s.get('display_name') or 'unnamed'})" for s in matches]
        raise _ambiguous(handle, "Speakers", names)
    return matches[0]
