"""Persistence operations for Meetings and their derived Segments."""

from models import Speaker, Segment


def rebuild_speakers_and_segments(db, meeting, aligned, speaker_info, speaker_id_service):
    """Preserve edits, delete old derived rows, and save Speakers and Segments."""
    EDIT_TIME_TOLERANCE = 1.5

    existing_segments = (
        db.query(Segment)
        .filter(Segment.meeting_id == meeting.id)
        .order_by(Segment.order)
        .all()
    )
    edited_segments = [
        {"start": s.start_time, "end": s.end_time, "text": s.text}
        for s in existing_segments if s.is_edited
    ]

    db.query(Segment).filter(Segment.meeting_id == meeting.id).delete()
    db.query(Speaker).filter(Speaker.meeting_id == meeting.id).delete()
    db.commit()

    speaker_map = {}
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
        db.flush()
        speaker_map[label] = speaker

    if any(s["speaker"] == "UNKNOWN" for s in aligned):
        unk = Speaker(
            meeting_id=meeting.id,
            label="UNKNOWN",
            display_name="Unknown",
            color="#9ca3af",
        )
        db.add(unk)
        db.flush()
        speaker_map["UNKNOWN"] = unk

    for i, seg in enumerate(aligned):
        speaker = speaker_map.get(seg["speaker"])
        text = seg["text"]
        is_edited = False

        for edited in edited_segments:
            if (abs(seg["start"] - edited["start"]) < EDIT_TIME_TOLERANCE
                    and abs(seg["end"] - edited["end"]) < EDIT_TIME_TOLERANCE):
                text = edited["text"]
                is_edited = True
                break

        db.add(Segment(
            meeting_id=meeting.id,
            speaker_id=speaker.id if speaker else None,
            start_time=seg["start"],
            end_time=seg["end"],
            text=text,
            original_text=seg["text"],
            order=i,
            is_edited=is_edited,
            confidence=seg.get("confidence"),
            corrections=[] if is_edited else seg.get("corrections", []),
        ))

    for spk in speaker_map.values():
        segs = [s for s in aligned if s["speaker"] == spk.label]
        spk.segment_count = len(segs)
        spk.total_speaking_time = sum(s["end"] - s["start"] for s in segs)

    db.commit()
