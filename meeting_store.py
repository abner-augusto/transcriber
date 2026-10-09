"""Persistence operations for Meetings and their derived Segments."""

from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import func

from models import Speaker, Segment
from services.speaker_id_service import SPEAKER_COLORS
from tasks.dual_track import HOST_SPEAKER
from transcript.speaker_carry import match_by_overlap

# An edited Segment survives a rebuild when a derived Segment starts and ends
# within this many seconds of it.
EDIT_TIME_TOLERANCE = 1.5

# Speakers the user added by hand; they own no Turns, so they are never rebuilt away.
MANUAL_PREFIX = "MANUAL_"


def refresh_speaker_stats(db, speaker) -> None:
    """Recount a Speaker's Segments and speaking time from the rows that exist now."""
    count, speaking_time = db.query(
        func.count(Segment.id),
        func.coalesce(func.sum(Segment.end_time - Segment.start_time), 0),
    ).filter(Segment.speaker_id == speaker.id).one()
    speaker.segment_count = count
    speaker.total_speaking_time = speaking_time


def labels_with_segments(aligned) -> list[str]:
    """The Diarizer labels that own at least one Segment: the ones that become Speakers.

    A Diarizer can report a label whose Turns never cover a Word (echo, crosstalk
    under another voice). Naming it would add an empty "Participant N".
    """
    return sorted({segment["speaker"] for segment in aligned} - {"UNKNOWN"})


@dataclass
class _UserEdits:
    """What the user did to Speakers and Segment owners, copied before the rows are deleted."""

    # label -> (display_name, color) of Speakers the user named or added
    manual: dict[str, tuple[str, str]] = field(default_factory=dict)
    # label -> Segment intervals, for every Speaker
    intervals: dict[str, list[tuple[float, float]]] = field(default_factory=dict)
    # (start, end, target label) of Segments the user moved to another Speaker
    reassigned: list[tuple[float, float, str]] = field(default_factory=list)


def _user_edits(db, meeting) -> _UserEdits:
    edits = _UserEdits()
    speakers = db.query(Speaker).filter(Speaker.meeting_id == meeting.id).all()
    labels = {speaker.id: speaker.label for speaker in speakers}
    for speaker in speakers:
        if speaker.identified_by == "manual":
            edits.manual[speaker.label] = (speaker.display_name, speaker.color)
        edits.intervals[speaker.label] = []
    for segment in (
        db.query(Segment).filter(Segment.meeting_id == meeting.id).order_by(Segment.order).all()
    ):
        label = labels.get(segment.speaker_id)
        if label is None:
            continue
        edits.intervals[label].append((segment.start_time, segment.end_time))
        if segment.speaker_edited:
            edits.reassigned.append((segment.start_time, segment.end_time, label))
    return edits


def rebuild_speakers_and_segments(
    db, meeting, aligned, speaker_info, speaker_id_service,
    *, keep: Literal["labels", "overlap"],
):
    """Replace the Meeting's Speakers and Segments, preserving what the user edited.

    Edited Segment text always survives. `keep` says whether the Turns are the same
    ones as before: "labels" (Re-identify) keeps manual Speaker names by label and
    re-applies Segment reassignments; "overlap" (new Turns) carries a manual name to
    the new label that overlaps it most and drops reassignments.
    """
    edited = _edited_segments(db, meeting)
    prior = _user_edits(db, meeting)
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

    if keep == "labels":
        _carry_names_by_label(db, meeting, speakers, prior)
    else:
        _carry_names_by_overlap(speakers, aligned, prior)
    db.flush()

    written = _write_segments(db, meeting, aligned, speakers, edited)
    _finish_rebuild(db, speakers, written, prior.reassigned if keep == "labels" else [])


def _carry_names_by_label(db, meeting, speakers: dict[str, Speaker], prior: _UserEdits) -> None:
    """The Turns are unchanged, so a label is the same person: the user's name wins."""
    for label, (display_name, color) in prior.manual.items():
        if label in speakers:
            speakers[label].display_name = display_name
            speakers[label].identified_by = "manual"
        elif label.startswith(MANUAL_PREFIX):
            speakers[label] = Speaker(
                meeting_id=meeting.id, label=label, display_name=display_name,
                color=color, identified_by="manual",
            )
            db.add(speakers[label])


def _carry_names_by_overlap(speakers: dict[str, Speaker], aligned, prior: _UserEdits) -> None:
    """New Turns: a name follows the new label that speaks over the same stretches."""
    for label, (display_name, _) in prior.manual.items():
        if label == HOST_SPEAKER and label in speakers:
            speakers[label].display_name = display_name
            speakers[label].identified_by = "manual"

    new: dict[str, list[tuple[float, float]]] = {}
    for segment in aligned:
        if segment["speaker"] not in ("UNKNOWN", HOST_SPEAKER) and segment["speaker"] in speakers:
            new.setdefault(segment["speaker"], []).append((segment["start"], segment["end"]))
    old = {label: spans for label, spans in prior.intervals.items() if label != HOST_SPEAKER}
    for old_label, new_label in match_by_overlap(old, new).items():
        if old_label in prior.manual:
            speakers[new_label].display_name = prior.manual[old_label][0]
            speakers[new_label].identified_by = "manual"


def replace_segments(db, meeting, aligned):
    """Replace the Meeting's Segments, keeping its Speakers, edited text and reassignments."""
    edited = _edited_segments(db, meeting)
    prior = _user_edits(db, meeting)
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
    written = _write_segments(db, meeting, aligned, speakers, edited)
    _finish_rebuild(db, speakers, written, prior.reassigned)


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


def _claim_nearest(records, spans) -> dict[int, object]:
    """Pair each (start, end, payload) record with at most one span, and each span with at most one record.

    A span is a candidate when both its start and end are within EDIT_TIME_TOLERANCE
    of the record's. Records claim greedily, nearest first (by |Δstart| + |Δend|), so
    an exact match always wins and a neighbour is never dragged along.
    Returns {span index: payload}.
    """
    candidates = sorted(
        (abs(span[0] - start) + abs(span[1] - end), record_index, span_index)
        for record_index, (start, end, _) in enumerate(records)
        for span_index, span in enumerate(spans)
        if abs(span[0] - start) < EDIT_TIME_TOLERANCE and abs(span[1] - end) < EDIT_TIME_TOLERANCE
    )
    claimed: dict[int, object] = {}
    used_records = set()
    for _, record_index, span_index in candidates:
        if record_index in used_records or span_index in claimed:
            continue
        used_records.add(record_index)
        claimed[span_index] = records[record_index][2]
    return claimed


def _write_segments(db, meeting, aligned, speakers: dict[str, Speaker], edits) -> list[Segment]:
    written = []
    edited_texts = _claim_nearest(edits, [(seg["start"], seg["end"]) for seg in aligned])
    for i, seg in enumerate(aligned):
        edited_text = edited_texts.get(i)
        speaker = speakers.get(seg["speaker"])
        segment = Segment(
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
        )
        db.add(segment)
        written.append(segment)
    db.flush()
    return written


def _finish_rebuild(db, speakers: dict[str, Speaker], written, reassigned) -> None:
    """Re-apply Segment reassignments, recount every Speaker, drop diarized ones left empty."""
    targets = _claim_nearest(
        [record for record in reassigned if record[2] in speakers],
        [(segment.start_time, segment.end_time) for segment in written],
    )
    for index, label in targets.items():
        written[index].speaker_id = speakers[label].id
        written[index].speaker_edited = True
    db.flush()

    for label, speaker in list(speakers.items()):
        refresh_speaker_stats(db, speaker)
        if speaker.segment_count == 0 and not label.startswith(MANUAL_PREFIX):
            db.delete(speaker)
            del speakers[label]
    db.commit()
