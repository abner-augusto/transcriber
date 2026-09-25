"""Database boundary for the pure Vocabulary Correction value."""

from difflib import SequenceMatcher
import logging

from models import VocabularyEntry
from transcript.vocabulary_correction import (
    MisheardForm,
    VocabularyCorrection,
    normalize_vocabulary_text,
)

log = logging.getLogger(__name__)

# A learned phrase longer than this is a rewrite, not a correction.
MAX_LEARNED_PHRASE_LENGTH = 100
# Short lowercase words are common words, not names or technical terms.
MIN_LOWERCASE_TERM_LENGTH = 5


def vocabulary_correction_for_meeting(db, meeting, *, enabled: bool = True):
    if not enabled:
        return None
    forms = load_misheard_forms(db)
    return VocabularyCorrection.for_meeting(meeting.vocabulary, forms)


def load_misheard_forms(db):
    """Load learned forms at the database boundary for correction and benchmarks."""
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
    """Learn Vocabulary from a manual Segment edit.

    A replaced or inserted phrase becomes a term; a replaced phrase is also
    recorded as a Misheard Form of its term. Putting back what the Engine heard
    in place of one of the Segment's Corrections is an undo and teaches nothing.
    """
    if not before or not after or before.strip() == after.strip():
        return

    undone = {
        (normalize_vocabulary_text(c["term"]), normalize_vocabulary_text(c["heard"]))
        for c in corrections
    }
    old_words, new_words = before.split(), after.split()
    terms: list[str] = []
    forms: list[tuple[str, str]] = []
    for op, i1, i2, j1, j2 in SequenceMatcher(None, old_words, new_words).get_opcodes():
        new_phrase = " ".join(new_words[j1:j2]).strip()
        if not _worth_learning(new_phrase):
            continue
        if op == "insert":
            terms.append(new_phrase)
        elif op == "replace":
            old_phrase = " ".join(old_words[i1:i2])
            if (normalize_vocabulary_text(old_phrase), normalize_vocabulary_text(new_phrase)) in undone:
                continue
            if abs(len(new_phrase) - len(old_phrase)) < len(old_phrase):
                terms.append(new_phrase)
                forms.append((old_phrase, new_phrase))

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


def _worth_learning(phrase: str) -> bool:
    if not 2 <= len(phrase) < MAX_LEARNED_PHRASE_LENGTH:
        return False
    return not (phrase.islower() and len(phrase) < MIN_LOWERCASE_TERM_LENGTH)


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
