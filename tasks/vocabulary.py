"""Database boundary for the pure Vocabulary Correction value."""

import logging
import re

from models import Meeting, RejectedForm, Segment, VocabularyEntry
from transcript.vocabulary_correction import (
    MisheardForm,
    VocabularyCorrection,
    capitalized_mid_sentence,
    learned_from_edit,
    normalize_vocabulary_text,
    parse_vocabulary,
    without_edge_punctuation,
)

log = logging.getLogger(__name__)


def vocabulary_correction_for_meeting(db, meeting, *, enabled: bool = True):
    if not enabled:
        return None
    forms = load_misheard_forms(db)
    rejected = [(row.heard, row.term) for row in db.query(RejectedForm).all()]
    return VocabularyCorrection.for_meeting(meeting.vocabulary, forms, rejected)


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
    meeting = db.get(Meeting, meeting_id)
    known = [
        *parse_vocabulary(meeting.vocabulary if meeting else None),
        *(
            name.strip()
            for name in re.split(r"[,\n]", (meeting.participants if meeting else None) or "")
            if name.strip()
        ),
    ]
    proper = capitalized_mid_sentence(
        text for (text,) in db.query(Segment.text).filter(Segment.meeting_id == meeting_id)
    )
    terms, forms = learned_from_edit(before, after, undone=undone, known=known, proper=proper)

    for term in dict.fromkeys(terms):
        existing = db.query(VocabularyEntry).filter(VocabularyEntry.term == term).first()
        if existing:
            existing.frequency += 1
        else:
            db.add(VocabularyEntry(term=term, source_meeting_id=meeting_id))
    db.flush()  # so a term added above is found when its Misheard Form is recorded

    for heard, term in forms:
        _record_misheard_form(db, heard=heard, term=term)

    try:
        db.commit()
    except Exception:
        log.warning("Vocabulary learning failed for Meeting %s", meeting_id, exc_info=True)
        db.rollback()


def teach_confirmed_correction(db, *, heard: str, term: str, meeting_id: str) -> None:
    """Persist what confirming a Correction teaches: the term, and heard as its Misheard Form."""
    normalized_term = normalize_vocabulary_text(term)
    if not any(
        normalize_vocabulary_text(row.term) == normalized_term
        for row in db.query(VocabularyEntry).all()
    ):
        db.add(VocabularyEntry(term=term, source_meeting_id=meeting_id))
        db.flush()  # so the entry is found when its Misheard Form is recorded
    _record_misheard_form(db, heard=without_edge_punctuation(heard), term=term)


def record_rejected_form(db, *, heard: str, term: str, meeting_id: str) -> None:
    """Persist a Rejected Form (once) and stop the term's entry from learning it as a Misheard Form."""
    normalized_heard, normalized_term = normalize_vocabulary_text(heard), normalize_vocabulary_text(term)
    if not any(
        (normalize_vocabulary_text(row.heard), normalize_vocabulary_text(row.term))
        == (normalized_heard, normalized_term)
        for row in db.query(RejectedForm).all()
    ):
        db.add(RejectedForm(heard=heard, term=term, source_meeting_id=meeting_id))
    for entry in db.query(VocabularyEntry).all():
        if normalize_vocabulary_text(entry.term) != normalized_term:
            continue
        forms = entry.misheard_as or []
        kept = [
            form for form in forms
            if normalize_vocabulary_text(form.get("form", "")) != normalized_heard
        ]
        if len(kept) != len(forms):
            entry.misheard_as = kept


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
