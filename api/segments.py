from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from database import get_db
from meeting_store import refresh_speaker_stats
from models import Meeting, MeetingStatus, Segment, Speaker
from tasks.vocabulary import learn_from_edit

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
    db.flush()
    if previous is not None:
        refresh_speaker_stats(db, previous)
    refresh_speaker_stats(db, speaker)
    db.commit()
    return segment.to_dict()
