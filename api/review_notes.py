"""Review Notes: questions, comments and suggestions anchored at a time range of a Meeting."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

import jobs
from api.segments import (
    SplitSegmentRequest, UpdateSegmentSpeakerRequest, UpdateSegmentTextRequest, require_editable,
    split_segment, update_segment_speaker, update_segment_text,
)
from api.speaker_profiles import SaveFromSpeakerRequest, save_profile_from_speaker
from api.speakers import (
    AddSpeakerRequest, MergeSpeakersRequest, UpdateSpeakerRequest, add_speaker,
    merge_speakers, update_speaker,
)
from database import get_db
from meeting_store import segment_for_range
from models import Meeting, ReviewNote, Speaker

meeting_notes_router = APIRouter(prefix="/api/meetings", tags=["review-notes"])
router = APIRouter(prefix="/api/notes", tags=["review-notes"])

# "system" is reserved for notes the app itself will leave (issue 08); v1 does not create it.
AUTHORS = ("agent", "user")
KINDS = ("comment", "question", "text", "speaker_name", "speaker_move", "speaker_merge", "split")
SUGGESTION_KINDS = ("text", "speaker_name", "speaker_move", "speaker_merge", "split")
RESOLVED = ("accepted", "dismissed", "done")
STATUS_FILTERS = ("open", "answered", "resolved", "all")


class CreateNoteRequest(BaseModel):
    start_time: float
    end_time: float
    kind: str
    body: str
    author: str
    payload: dict | None = None


class AnswerNoteRequest(BaseModel):
    answer: str


class CloseNoteRequest(BaseModel):
    reply: str | None = None


class AcceptNoteRequest(BaseModel):
    learn: bool = True
    save_profile: bool = True


def _speaker(db: Session, meeting_id: str, label) -> Speaker | None:
    if not isinstance(label, str):
        return None
    return db.query(Speaker).filter(Speaker.meeting_id == meeting_id, Speaker.label == label).first()


def _text(payload: dict, key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(400, f"payload.{key} is required")
    return value


def _validated_payload(db: Session, meeting_id: str, req: CreateNoteRequest) -> dict | None:
    payload = req.payload
    if req.kind in ("comment", "question"):
        if payload:
            raise HTTPException(400, f"a {req.kind} takes no payload")
        return None
    if not payload:
        raise HTTPException(400, f"a {req.kind} note needs a payload")

    if req.kind == "text":
        _text(payload, "proposed_text")
        expected = _text(payload, "expected_text")
        segment = segment_for_range(db, meeting_id, req.start_time, req.end_time)
        if segment is None:
            raise HTTPException(400, "no Segment at this range")
        if segment.text != expected:
            raise HTTPException(400, "expected_text is not the Segment's current text")
    elif req.kind == "speaker_name":
        _text(payload, "name")
        if _speaker(db, meeting_id, payload.get("label")) is None:
            raise HTTPException(400, "label is not a Speaker of this Meeting")
    elif req.kind == "speaker_move":
        if segment_for_range(db, meeting_id, req.start_time, req.end_time) is None:
            raise HTTPException(400, "no Segment at this range")
        if "target_label" in payload:
            if _speaker(db, meeting_id, payload["target_label"]) is None:
                raise HTTPException(400, "target_label is not a Speaker of this Meeting")
        else:
            _text(payload, "new_name")
    elif req.kind == "split":
        segment = segment_for_range(db, meeting_id, req.start_time, req.end_time)
        if segment is None:
            raise HTTPException(400, "no Segment at this range")
        if segment.is_edited:
            raise HTTPException(400, "the Segment is edited; revert it first")
        at = payload.get("at")
        if isinstance(at, bool) or not isinstance(at, (int, float)):
            raise HTTPException(400, "payload.at is required")
        if not segment.start_time < at < segment.end_time:
            raise HTTPException(400, "payload.at must fall inside the Segment")
        _text(payload, "preview")
        if "target_label" in payload and "new_name" in payload:
            raise HTTPException(400, "give target_label or new_name, not both")
        if "target_label" in payload:
            if _speaker(db, meeting_id, payload["target_label"]) is None:
                raise HTTPException(400, "target_label is not a Speaker of this Meeting")
        elif "new_name" in payload:
            _text(payload, "new_name")
    elif req.kind == "speaker_merge":
        source, target = payload.get("source_label"), payload.get("target_label")
        if _speaker(db, meeting_id, source) is None or _speaker(db, meeting_id, target) is None:
            raise HTTPException(400, "source_label and target_label must be Speakers of this Meeting")
        if source == target:
            raise HTTPException(400, "source_label and target_label must differ")
    return payload


@meeting_notes_router.post("/{meeting_id}/notes")
def create_note(meeting_id: str, req: CreateNoteRequest, db: Session = Depends(get_db)):
    if db.get(Meeting, meeting_id) is None:
        raise HTTPException(404, "Meeting not found")
    if req.start_time > req.end_time:
        raise HTTPException(400, "start_time must not be after end_time")
    if req.kind not in KINDS:
        raise HTTPException(400, f"kind must be one of: {', '.join(KINDS)}")
    if req.author not in AUTHORS:
        raise HTTPException(400, f"author must be one of: {', '.join(AUTHORS)}")
    if req.author == "user" and req.kind != "comment":
        raise HTTPException(400, "a user note is a comment")
    body = req.body.strip()
    if not body:
        raise HTTPException(400, "body is required")
    payload = _validated_payload(db, meeting_id, req)

    note = ReviewNote(
        meeting_id=meeting_id, start_time=req.start_time, end_time=req.end_time,
        author=req.author, kind=req.kind, body=body, payload=payload, status="open",
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    jobs.notify_meeting_changed(meeting_id)
    return note.to_dict()


@meeting_notes_router.get("/{meeting_id}/notes")
def list_notes(meeting_id: str, status: str = "all", db: Session = Depends(get_db)):
    if status not in STATUS_FILTERS:
        raise HTTPException(400, f"status must be one of: {', '.join(STATUS_FILTERS)}")
    if db.get(Meeting, meeting_id) is None:
        raise HTTPException(404, "Meeting not found")
    query = db.query(ReviewNote).filter(ReviewNote.meeting_id == meeting_id)
    if status == "resolved":
        query = query.filter(ReviewNote.status.in_(RESOLVED))
    elif status != "all":
        query = query.filter(ReviewNote.status == status)
    return [note.to_dict() for note in query.order_by(ReviewNote.start_time, ReviewNote.created_at).all()]


def _get_note(db: Session, note_id: str) -> ReviewNote:
    note = db.get(ReviewNote, note_id)
    if note is None:
        raise HTTPException(404, "Note not found")
    return note


def _resolve(db: Session, note: ReviewNote, status: str) -> None:
    note.status = status
    note.resolved_at = datetime.utcnow()
    db.commit()
    jobs.notify_meeting_changed(note.meeting_id)


def _conflict_unless(found, message: str):
    if found is None:
        raise HTTPException(409, message)
    return found


def _apply_speaker_name(db: Session, note: ReviewNote, req: AcceptNoteRequest) -> str | None:
    payload = note.payload
    speaker = _conflict_unless(
        _speaker(db, note.meeting_id, payload["label"]), "the Speaker no longer exists"
    )
    update_speaker(speaker.id, UpdateSpeakerRequest(display_name=payload["name"]), db)
    if not req.save_profile:
        return None
    try:
        save_profile_from_speaker(
            SaveFromSpeakerRequest(speaker_id=speaker.id, meeting_id=note.meeting_id, name=payload["name"]),
            db,
        )
    except HTTPException as error:
        return f"Voice Profile not saved: {error.detail}"
    except Exception as error:  # e.g. ffmpeg failed; the rename already happened
        db.rollback()
        return f"Voice Profile not saved: {error}"
    return None


def _target_speaker_id(db: Session, note: ReviewNote) -> str:
    """The Speaker a speaker_move or split note hands a Segment to; `new_name` adds it first."""
    payload = note.payload
    if "target_label" in payload:
        return _conflict_unless(
            _speaker(db, note.meeting_id, payload["target_label"]), "the Speaker no longer exists"
        ).id
    return add_speaker(note.meeting_id, AddSpeakerRequest(display_name=payload["new_name"]), db)["id"]


def _apply(db: Session, note: ReviewNote, req: AcceptNoteRequest) -> str | None:
    """Run the suggestion through the same routes a manual edit uses. Returns a warning, if any."""
    payload = note.payload
    if note.kind == "speaker_name":
        return _apply_speaker_name(db, note, req)

    if note.kind == "speaker_merge":
        source = _conflict_unless(_speaker(db, note.meeting_id, payload["source_label"]), "the Speaker no longer exists")
        target = _conflict_unless(_speaker(db, note.meeting_id, payload["target_label"]), "the Speaker no longer exists")
        merge_speakers(MergeSpeakersRequest(source_id=source.id, target_id=target.id), db)
        return None

    segment = _conflict_unless(
        segment_for_range(db, note.meeting_id, note.start_time, note.end_time),
        "the passage no longer matches a Segment",
    )
    if note.kind == "text":
        if segment.text != payload["expected_text"]:
            raise HTTPException(409, "the Segment changed since the suggestion")
        update_segment_text(segment.id, UpdateSegmentTextRequest(text=payload["proposed_text"], learn=req.learn), db)
    elif note.kind == "split":
        if segment.is_edited:  # before add_speaker, so a refused split leaves no new Speaker behind
            raise HTTPException(409, "the Segment changed since the suggestion")
        target_id = _target_speaker_id(db, note) if ("target_label" in payload or "new_name" in payload) else None
        split_segment(segment.id, SplitSegmentRequest(at=payload["at"], speaker_id=target_id), db)
    else:  # speaker_move
        update_segment_speaker(segment.id, UpdateSegmentSpeakerRequest(speaker_id=_target_speaker_id(db, note)), db)
    return None


@router.post("/{note_id}/accept")
def accept_note(note_id: str, req: AcceptNoteRequest = AcceptNoteRequest(), db: Session = Depends(get_db)):
    """Apply a suggestion. This is the user's confirmation, so it teaches Vocabulary and Voice Profiles."""
    note = _get_note(db, note_id)
    if note.kind not in SUGGESTION_KINDS or note.status != "open":
        raise HTTPException(409, "only an open suggestion can be accepted")
    require_editable(db, note.meeting_id)
    warning = _apply(db, note, req)
    _resolve(db, note, "accepted")
    return {"note": note.to_dict(), "warning": warning}


@router.post("/{note_id}/answer")
def answer_note(note_id: str, req: AnswerNoteRequest, db: Session = Depends(get_db)):
    note = _get_note(db, note_id)
    if note.kind != "question" or note.status != "open":
        raise HTTPException(409, "only an open question can be answered")
    note.status = "answered"
    note.answer = req.answer
    db.commit()
    jobs.notify_meeting_changed(note.meeting_id)
    return note.to_dict()


@router.post("/{note_id}/done")
def close_note(note_id: str, req: CloseNoteRequest = CloseNoteRequest(), db: Session = Depends(get_db)):
    note = _get_note(db, note_id)
    closable = (note.kind == "question" and note.status == "answered") or (
        note.kind == "comment" and note.status == "open"
    )
    if not closable:
        raise HTTPException(409, "only an answered question or an open comment can be closed")
    note.reply = req.reply
    _resolve(db, note, "done")
    return note.to_dict()


@router.post("/{note_id}/dismiss")
def dismiss_note(note_id: str, db: Session = Depends(get_db)):
    note = _get_note(db, note_id)
    dismissible = (note.kind != "comment" and note.status == "open") or (
        note.kind == "question" and note.status == "answered"
    )
    if not dismissible:
        raise HTTPException(409, "this note cannot be dismissed")
    _resolve(db, note, "dismissed")
    return note.to_dict()
