from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import RejectedForm, VocabularyEntry

router = APIRouter(prefix="/api/vocabulary", tags=["vocabulary"])


@router.get("")
def list_vocabulary(db: Session = Depends(get_db)):
    entries = db.query(VocabularyEntry).order_by(VocabularyEntry.frequency.desc()).limit(200).all()
    return [e.to_dict() for e in entries]


@router.get("/rejected-forms")
def list_rejected_forms(db: Session = Depends(get_db)):
    """Heard forms the user said are not a Misheard Form of a term, newest first."""
    rows = db.query(RejectedForm).order_by(RejectedForm.created_at.desc()).all()
    return [row.to_dict() for row in rows]


@router.delete("/rejected-forms/{rejected_id}")
def delete_rejected_form(rejected_id: str, db: Session = Depends(get_db)):
    """Allow a heard form to be corrected to its term again, from the next Reprocessing."""
    row = db.query(RejectedForm).filter(RejectedForm.id == rejected_id).first()
    if not row:
        raise HTTPException(404, "Rejected Form not found")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.delete("/{entry_id}")
def delete_entry(entry_id: str, db: Session = Depends(get_db)):
    entry = db.query(VocabularyEntry).filter(VocabularyEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(404, "Entry not found")
    db.delete(entry)
    db.commit()
    return {"ok": True}


@router.delete("/{entry_id}/misheard-forms/{form}")
def delete_misheard_form(entry_id: str, form: str, db: Session = Depends(get_db)):
    """Stop correcting one learned Misheard Form while keeping its term."""
    entry = db.query(VocabularyEntry).filter(VocabularyEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(404, "Entry not found")
    forms = entry.misheard_as or []
    kept = [item for item in forms if item.get("form") != form]
    if len(kept) == len(forms):
        raise HTTPException(404, "Misheard Form not found")
    entry.misheard_as = kept
    db.commit()
    return entry.to_dict()


@router.get("/suggest")
def suggest_vocabulary(db: Session = Depends(get_db)):
    """Return top learned terms formatted as a vocabulary string for Whisper prompts."""
    entries = (
        db.query(VocabularyEntry)
        .filter(VocabularyEntry.frequency >= 2)
        .order_by(VocabularyEntry.frequency.desc())
        .limit(50)
        .all()
    )
    terms = [e.term for e in entries]
    return {"terms": terms, "text": ", ".join(terms)}
