from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

import jobs
import preferences
from database import get_db
from meeting_store import refresh_speaker_stats
from models import Meeting, MeetingStatus, Segment, Speaker
from tasks.vocabulary import (
    learn_from_edit,
    record_rejected_form,
    teach_confirmed_correction,
    vocabulary_correction_for_meeting,
)
from transcript.segments import derive_segments
from transcript.vocabulary_correction import without_edge_punctuation
from transcript.words import words_from_stored

router = APIRouter(prefix="/api", tags=["segments"])


class UpdateSegmentTextRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=10000)
    # A UI edit is the user's own correction and teaches Vocabulary. A caller
    # that cannot hear the audio sends learn=false so its guesses become no rules.
    learn: bool = True


class UpdateSegmentSpeakerRequest(BaseModel):
    speaker_id: str


def require_editable(db: Session, meeting_id: str) -> None:
    """Refuse an edit while a Job is processing the Meeting.

    Reprocessing deletes and recreates every Segment and Speaker, so an edit
    made meanwhile would be lost or hit a row that no longer exists.
    """
    meeting = db.get(Meeting, meeting_id)
    if meeting is not None and meeting.status == MeetingStatus.PROCESSING:
        raise HTTPException(409, "Meeting is being processed; edit it when the Job finishes")


class SplitSegmentRequest(BaseModel):
    # Any time inside the Segment; the cut snaps to the nearest Word start.
    at: float
    speaker_id: str | None = None


# Segment times are copied from Word times, so they match within float noise.
TIME_TOLERANCE = 1e-6


def _words_between(meeting: Meeting, start: float, end: float, before: float | None = None):
    """The Meeting's stored Words that lie inside [start, end] (and start before `before`)."""
    return [
        word for word in words_from_stored(meeting.raw_transcription)
        if word.start >= start - TIME_TOLERANCE
        and word.end <= end + TIME_TOLERANCE
        and (before is None or word.start < before)
    ]


def _vocabulary_correction(db: Session, meeting: Meeting):
    return vocabulary_correction_for_meeting(
        db, meeting, enabled=preferences.load().vocabulary_correction.enabled
    )


def _take_derived(segment: Segment, derived: dict) -> None:
    """Make `segment` the derived Segment: its extent, text and Correction marks."""
    segment.end_time = derived["end"]
    segment.text = derived["text"]
    segment.original_text = derived["text"]
    segment.confidence = derived["confidence"]
    segment.corrections = derived["corrections"]


@router.get("/meetings/{meeting_id}/segments")
def list_segments(meeting_id: str, db: Session = Depends(get_db)):
    segments = (
        db.query(Segment)
        .options(joinedload(Segment.speaker))
        .filter(Segment.meeting_id == meeting_id)
        .order_by(Segment.order)
        .all()
    )
    return [s.to_dict() for s in segments]


@router.put("/segments/{segment_id}")
def update_segment_text(segment_id: str, req: UpdateSegmentTextRequest, db: Session = Depends(get_db)):
    segment = db.query(Segment).filter(Segment.id == segment_id).first()
    if not segment:
        raise HTTPException(404, "Segment not found")
    require_editable(db, segment.meeting_id)

    old_text = segment.original_text or segment.text
    undone_candidates = list(segment.corrections or [])
    segment.text = req.text
    segment.is_edited = True
    # An edited Segment keeps the user's text, so it has no Corrections left.
    segment.corrections = []
    db.commit()

    if req.learn:
        learn_from_edit(
            db, old_text, req.text,
            meeting_id=segment.meeting_id, corrections=undone_candidates,
        )

    jobs.notify_meeting_changed(segment.meeting_id)
    return segment.to_dict()


@router.post("/segments/{segment_id}/revert")
def revert_segment_text(segment_id: str, db: Session = Depends(get_db)):
    """Restore the Segment's derived text, undoing a manual edit.

    Teaches nothing. The edit cleared the Segment's Correction marks, so they
    come back on the next Reapply Vocabulary.
    """
    segment = db.query(Segment).filter(Segment.id == segment_id).first()
    if not segment:
        raise HTTPException(404, "Segment not found")
    require_editable(db, segment.meeting_id)
    if not segment.is_edited or segment.original_text is None:
        raise HTTPException(409, "Segment has no edit to revert")

    segment.text = segment.original_text
    segment.is_edited = False
    segment.corrections = []
    db.commit()
    jobs.notify_meeting_changed(segment.meeting_id)
    return segment.to_dict()


class CorrectionRef(BaseModel):
    # The Correction's own start time: its identity within the Segment.
    start: float


def _correction_target(db: Session, segment_id: str, start: float) -> tuple[Segment, int]:
    """The Segment and the index of the stored Correction starting at `start`, or HTTP 404/409."""
    segment = db.query(Segment).filter(Segment.id == segment_id).first()
    if not segment:
        raise HTTPException(404, "Segment not found")
    require_editable(db, segment.meeting_id)
    if segment.is_edited:
        raise HTTPException(409, "Segment was edited by hand; revert the edit first")
    for index, item in enumerate(segment.corrections or []):
        if abs(item["start"] - start) <= TIME_TOLERANCE:
            return segment, index
    raise HTTPException(409, "No Correction starts there")


@router.post("/segments/{segment_id}/corrections/confirm")
def confirm_correction(segment_id: str, req: CorrectionRef, db: Session = Depends(get_db)):
    """Accept a Vocabulary Correction: teach its heard form as a Misheard Form of the term."""
    segment, index = _correction_target(db, segment_id, req.start)
    corrections = [dict(item) for item in segment.corrections]
    item = corrections[index]
    if not item.get("confirmed"):
        teach_confirmed_correction(
            db, heard=item["heard"], term=item["term"], meeting_id=segment.meeting_id
        )
        item["confirmed"] = True
        segment.corrections = corrections  # a new list, so the JSON column saves
    db.commit()
    jobs.notify_meeting_changed(segment.meeting_id)
    return segment.to_dict()


@router.post("/segments/{segment_id}/corrections/reject")
def reject_correction(segment_id: str, req: CorrectionRef, db: Session = Depends(get_db)):
    """Undo a Vocabulary Correction everywhere: put the heard form back and never correct it again.

    The Segment stays derived (not ``is_edited``). Other Meetings keep their stored
    text until their next Reprocessing, which honours the Rejected Form.
    """
    segment, index = _correction_target(db, segment_id, req.start)
    corrections = [dict(item) for item in segment.corrections]
    item = corrections.pop(index)
    start, end = item.get("text_start"), item.get("text_end")
    if start is None or end is None or segment.text[start:end] != item["term"]:
        raise HTTPException(409, "Corrections predate their text offsets; reapply Vocabulary first")

    heard = without_edge_punctuation(item["heard"])
    record_rejected_form(db, heard=heard, term=item["term"], meeting_id=segment.meeting_id)

    shift = len(heard) - (end - start)
    for other in corrections:
        if other.get("text_start") is not None and other["text_start"] >= end:
            other["text_start"] += shift
            other["text_end"] += shift
    segment.text = segment.text[:start] + heard + segment.text[end:]
    if segment.original_text is not None:
        segment.original_text = segment.original_text[:start] + heard + segment.original_text[end:]
    segment.corrections = corrections
    db.commit()
    jobs.notify_meeting_changed(segment.meeting_id)
    return segment.to_dict()


@router.put("/segments/{segment_id}/speaker")
def update_segment_speaker(segment_id: str, req: UpdateSegmentSpeakerRequest, db: Session = Depends(get_db)):
    segment = db.query(Segment).filter(Segment.id == segment_id).first()
    if not segment:
        raise HTTPException(404, "Segment not found")
    require_editable(db, segment.meeting_id)

    speaker = db.get(Speaker, req.speaker_id)
    if speaker is None:
        raise HTTPException(404, "Speaker not found")
    if speaker.meeting_id != segment.meeting_id:
        raise HTTPException(400, "Speaker belongs to another Meeting")

    previous = db.get(Speaker, segment.speaker_id) if segment.speaker_id else None
    segment.speaker_id = speaker.id
    segment.speaker_edited = True
    db.flush()
    if previous is not None:
        refresh_speaker_stats(db, previous)
    refresh_speaker_stats(db, speaker)
    db.commit()
    jobs.notify_meeting_changed(segment.meeting_id)
    return segment.to_dict()


@router.post("/segments/{segment_id}/split")
def split_segment(segment_id: str, req: SplitSegmentRequest, db: Session = Depends(get_db)):
    """Cut a Segment in two at a Word start, and keep the cut for every Reprocessing.

    The cut is stored on the Meeting as a Split, so derivation breaks there again
    after Re-identify, Reapply Vocabulary and Re-diarize. `speaker_id` hands the
    second half to another Speaker (a normal reassignment).
    """
    segment = db.query(Segment).filter(Segment.id == segment_id).first()
    if not segment:
        raise HTTPException(404, "Segment not found")
    require_editable(db, segment.meeting_id)
    if segment.is_edited:
        raise HTTPException(409, "revert the edit first")
    meeting = db.get(Meeting, segment.meeting_id)

    following = (
        db.query(Segment)
        .filter(Segment.meeting_id == meeting.id, Segment.order == segment.order + 1)
        .first()
    )
    words = _words_between(
        meeting, segment.start_time, segment.end_time,
        before=following.start_time if following else None,
    )
    # Correct first, so the cut never lands inside a corrected multi-Word term.
    correction = _vocabulary_correction(db, meeting)
    corrected = correction.apply(words)[0] if correction else words
    if len(corrected) < 2:
        raise HTTPException(409, "this Segment has no Word boundary to cut at")
    cut = min(corrected[1:], key=lambda word: abs(word.start - req.at)).start

    halves = derive_segments(words, None, correction=correction, splits=[cut])
    if len(halves) != 2:
        raise HTTPException(409, "could not split here")

    target = None
    if req.speaker_id is not None:
        target = db.get(Speaker, req.speaker_id)
        if target is None:
            raise HTTPException(404, "Speaker not found")
        if target.meeting_id != meeting.id:
            raise HTTPException(400, "Speaker belongs to another Meeting")

    db.query(Segment).filter(
        Segment.meeting_id == meeting.id, Segment.order > segment.order
    ).update({Segment.order: Segment.order + 1}, synchronize_session="fetch")
    _take_derived(segment, halves[0])
    second = Segment(
        meeting_id=meeting.id,
        speaker_id=target.id if target else segment.speaker_id,
        start_time=halves[1]["start"],
        end_time=halves[1]["end"],
        order=segment.order + 1,
        speaker_edited=True if target else segment.speaker_edited,
    )
    _take_derived(second, halves[1])
    db.add(second)
    meeting.split_times = sorted({*(meeting.split_times or []), cut})

    db.flush()
    for speaker_id in {segment.speaker_id, second.speaker_id} - {None}:
        refresh_speaker_stats(db, db.get(Speaker, speaker_id))
    db.commit()
    jobs.notify_meeting_changed(meeting.id)
    return {"segments": [segment.to_dict(), second.to_dict()]}


@router.post("/segments/{segment_id}/unsplit")
def unsplit_segment(segment_id: str, db: Session = Depends(get_db)):
    """Join a Segment with the next one when a Split lies between them, and drop the Split."""
    segment = db.query(Segment).filter(Segment.id == segment_id).first()
    if not segment:
        raise HTTPException(404, "Segment not found")
    require_editable(db, segment.meeting_id)
    meeting = db.get(Meeting, segment.meeting_id)

    following = (
        db.query(Segment)
        .filter(Segment.meeting_id == meeting.id, Segment.order == segment.order + 1)
        .first()
    )
    split_times = meeting.split_times or []
    if following is None or not any(
        abs(time - following.start_time) <= TIME_TOLERANCE for time in split_times
    ):
        raise HTTPException(409, "no Split after this Segment")
    if segment.is_edited or following.is_edited:
        raise HTTPException(409, "revert the edit first")

    words = _words_between(meeting, segment.start_time, following.end_time)
    joined = derive_segments(words, None, correction=_vocabulary_correction(db, meeting))
    if len(joined) != 1:
        raise HTTPException(409, "could not join these Segments")

    _take_derived(segment, joined[0])
    absorbed_speaker_id = following.speaker_id
    db.delete(following)
    db.query(Segment).filter(
        Segment.meeting_id == meeting.id, Segment.order > following.order
    ).update({Segment.order: Segment.order - 1}, synchronize_session="fetch")
    meeting.split_times = [
        time for time in split_times if abs(time - following.start_time) > TIME_TOLERANCE
    ]

    db.flush()
    for speaker_id in {segment.speaker_id, absorbed_speaker_id} - {None}:
        refresh_speaker_stats(db, db.get(Speaker, speaker_id))
    db.commit()
    jobs.notify_meeting_changed(meeting.id)
    return segment.to_dict()
