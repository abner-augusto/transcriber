"""Database boundary for the pure Vocabulary Correction value."""

import logging

from models import VocabularyEntry
from transcript.vocabulary_correction import (
    MisheardForm,
    VocabularyCorrection,
    learned_from_edit,
    normalize_vocabulary_text,
)

log = logging.getLogger(__name__)


def vocabulary_correction_for_meeting(db, meeting, *, enabled: bool = True):
    if not enabled:
        return None
    forms = load_misheard_forms(db)
    return VocabularyCorrection.for_meeting(meeting.vocabulary, forms)


def load_misheard_forms(db):
    """Load learned forms at the database boundary for correction."""
    return [
        MisheardForm(heard=item["form"], term=entry.term, count=item["count"])
        for entry in db.query(VocabularyEntry).all()
        for item in (entry.misheard_as or [])
        if isinstance(item, dict) and isinstance(item.get("form"), str)
        and isinstance(item.get("count"), int)
    ]


def learn_from_edit(
    db, before: str, after: str, *, meeting_id: str, corrections: list[dict]
) -> None:
    """Persist the Vocabulary a manual Segment edit teaches (see ``learned_from_edit``)."""
    undone = {(c["term"], c["heard"]) for c in corrections}
    terms, forms = learned_from_edit(before, after, undone=undone)

    for term in dict.fromkeys(terms):
        existing = db.query(VocabularyEntry).filter(VocabularyEntry.term == term).first()
        if existing:
            existing.frequency += 1
        else:
            db.add(VocabularyEntry(term=term, source_meeting_id=meeting_id))

    for heard, term in forms:
        _record_misheard_form(db, heard=heard, term=term)

    try:
        db.commit()
    except Exception:
        log.warning("Vocabulary learning failed for Meeting %s", meeting_id, exc_info=True)
        db.rollback()


def _record_misheard_form(db, *, heard: str, term: str) -> None:
    normalized_term = normalize_vocabulary_text(term)
    entry = next((
        row for row in db.query(VocabularyEntry).all()
        if normalize_vocabulary_text(row.term) == normalized_term
    ), None)
    if entry is None:
        return
    forms = [dict(form) for form in (entry.misheard_as or [])]
    normalized_heard = normalize_vocabulary_text(heard)
    existing = next(
        (form for form in forms if normalize_vocabulary_text(form.get("form", "")) == normalized_heard),
        None,
    )
    if existing:
        existing["count"] += 1
    else:
        forms.append({"form": heard, "count": 1})
    entry.misheard_as = forms
