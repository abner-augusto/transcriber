"""Persistence operations for Meetings and their derived Segments."""

from models import Speaker, Segment
from services.speaker_id_service import SPEAKER_COLORS

# An edited Segment survives a rebuild when a derived Segment starts and ends
# within this many seconds of it.
EDIT_TIME_TOLERANCE = 1.5


def labels_with_segments(aligned) -> list[str]:
    """The Diarizer labels that own at least one Segment: the ones that become Speakers.

    A Diarizer can report a label whose Turns never cover a Word (echo, crosstalk
    under another voice). Naming it would add an empty "Participant N".
    """
    return sorted({segment["speaker"] for segment in aligned} - {"UNKNOWN"})


def rebuild_speakers_and_segments(db, meeting, aligned, speaker_info, speaker_id_service):
    """Replace the Meeting's Speakers and Segments, preserving edited Segment text."""
    edited = _edited_segments(db, meeting)
    db.query(Segment).filter(Segment.meeting_id == meeting.id).delete()
    db.query(Speaker).filter(Speaker.meeting_id == meeting.id).delete()
    db.commit()

    speakers = {}
    for i, (label, info) in enumerate(sorted(speaker_info.items())):
        speaker = Speaker(
            meeting_id=meeting.id,
            label=label,
            display_name=info["name"],
            color=speaker_id_service.get_color(i),
            identified_by=info.get("identified_by"),
            confidence=info.get("confidence"),
        )
        db.add(speaker)
        speakers[label] = speaker

    if any(s["speaker"] == "UNKNOWN" for s in aligned):
        unknown = Speaker(
            meeting_id=meeting.id,
            label="UNKNOWN",
            display_name="Unknown",
            color="#9ca3af",
        )
        db.add(unknown)
        speakers["UNKNOWN"] = unknown
    db.flush()

    _write_segments(db, meeting, aligned, speakers, edited)


def replace_segments(db, meeting, aligned):
    """Replace the Meeting's Segments, keeping its Speakers and edited Segment text."""
    edited = _edited_segments(db, meeting)
    speakers = {
        speaker.label: speaker
        for speaker in db.query(Speaker).filter(Speaker.meeting_id == meeting.id).all()
    }
    # Only labels that owned Segments became Speakers, so a re-derivation (a new
    # smoothing penalty, say) can hand Words to a label that has none yet.
    for label in labels_with_segments(aligned):
        if label not in speakers:
            index = len([s for s in speakers if s != "UNKNOWN"])
            speakers[label] = Speaker(
                meeting_id=meeting.id,
                label=label,
                display_name=f"Participant {index + 1}",
                color=SPEAKER_COLORS[index % len(SPEAKER_COLORS)],
            )
            db.add(speakers[label])
    db.query(Segment).filter(Segment.meeting_id == meeting.id).delete()
    db.flush()
    _write_segments(db, meeting, aligned, speakers, edited)


def _edited_segments(db, meeting) -> list[tuple[float, float, str]]:
    """(start, end, text) of edited Segments, copied before the rows are deleted."""
    return [
        (segment.start_time, segment.end_time, segment.text)
        for segment in (
            db.query(Segment)
            .filter(Segment.meeting_id == meeting.id, Segment.is_edited.is_(True))
            .order_by(Segment.order)
            .all()
        )
    ]


def _write_segments(db, meeting, aligned, speakers: dict[str, Speaker], edits):
    for i, seg in enumerate(aligned):
        edited_text = next((
            text for start, end, text in edits
            if abs(seg["start"] - start) < EDIT_TIME_TOLERANCE
            and abs(seg["end"] - end) < EDIT_TIME_TOLERANCE
        ), None)
        speaker = speakers.get(seg["speaker"])
        db.add(Segment(
            meeting_id=meeting.id,
            speaker_id=speaker.id if speaker else None,
            start_time=seg["start"],
            end_time=seg["end"],
            text=seg["text"] if edited_text is None else edited_text,
            original_text=seg["text"],
            order=i,
            is_edited=edited_text is not None,
            confidence=seg.get("confidence"),
            corrections=seg.get("corrections", []) if edited_text is None else [],
        ))

    for speaker in speakers.values():
        spoken = [s for s in aligned if s["speaker"] == speaker.label]
        speaker.segment_count = len(spoken)
        speaker.total_speaking_time = sum(s["end"] - s["start"] for s in spoken)

    db.commit()
