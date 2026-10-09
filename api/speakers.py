from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.segments import require_editable
from database import get_db
from meeting_store import refresh_speaker_stats
from models import Meeting, Speaker, Segment
from services.speaker_id_service import SPEAKER_COLORS

router = APIRouter(prefix="/api/speakers", tags=["speakers"])
meeting_speakers_router = APIRouter(prefix="/api/meetings", tags=["speakers"])

MAX_DISPLAY_NAME_LENGTH = 200


class AddSpeakerRequest(BaseModel):
    display_name: str


class UpdateSpeakerRequest(BaseModel):
    display_name: str | None = None
    color: str | None = None


class MergeSpeakersRequest(BaseModel):
    source_id: str
    target_id: str


@meeting_speakers_router.post("/{meeting_id}/speakers")
def add_speaker(meeting_id: str, req: AddSpeakerRequest, db: Session = Depends(get_db)):
    """Add a Speaker the Diarizer missed, e.g. when it put two people under one label."""
    if db.get(Meeting, meeting_id) is None:
        raise HTTPException(404, "Meeting not found")
    require_editable(db, meeting_id)
    display_name = req.display_name.strip()
    if not display_name:
        raise HTTPException(400, "display_name is required")
    if len(display_name) > MAX_DISPLAY_NAME_LENGTH:
        raise HTTPException(400, f"display_name is longer than {MAX_DISPLAY_NAME_LENGTH} characters")

    existing = db.query(Speaker).filter(Speaker.meeting_id == meeting_id).all()
    used = {speaker.label for speaker in existing}
    number = 1
    while f"MANUAL_{number}" in used:
        number += 1

    speaker = Speaker(
        meeting_id=meeting_id,
        label=f"MANUAL_{number}",
        display_name=display_name,
        color=SPEAKER_COLORS[len(existing) % len(SPEAKER_COLORS)],
        identified_by="manual",
        segment_count=0,
        total_speaking_time=0.0,
    )
    db.add(speaker)
    db.commit()
    db.refresh(speaker)
    return speaker.to_dict()


@router.put("/{speaker_id}")
def update_speaker(speaker_id: str, req: UpdateSpeakerRequest, db: Session = Depends(get_db)):
    speaker = db.query(Speaker).filter(Speaker.id == speaker_id).first()
    if not speaker:
        raise HTTPException(404, "Speaker not found")
    require_editable(db, speaker.meeting_id)

    if req.display_name is not None:
        speaker.display_name = req.display_name
        speaker.identified_by = "manual"
    if req.color is not None:
        speaker.color = req.color

    db.commit()
    return speaker.to_dict()


@router.post("/merge")
def merge_speakers(req: MergeSpeakersRequest, db: Session = Depends(get_db)):
    source = db.query(Speaker).filter(Speaker.id == req.source_id).first()
    target = db.query(Speaker).filter(Speaker.id == req.target_id).first()

    if not source or not target:
        raise HTTPException(404, "Speaker not found")
    if source.meeting_id != target.meeting_id:
        raise HTTPException(400, "Speakers must be from the same meeting")
    require_editable(db, source.meeting_id)

    # Move all segments from source to target
    db.query(Segment).filter(Segment.speaker_id == source.id).update(
        {"speaker_id": target.id}, synchronize_session="fetch"
    )

    refresh_speaker_stats(db, target)

    # Delete source
    db.delete(source)
    db.commit()
    db.refresh(target)

    return target.to_dict()
