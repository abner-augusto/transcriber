"""Database boundary for the pure Vocabulary Correction value."""

from models import VocabularyEntry
from transcript.vocabulary_correction import MisheardForm, VocabularyCorrection


def vocabulary_correction_for_meeting(db, meeting):
    from preferences import load_preferences

    preferences = load_preferences().get("vocabulary_correction", {})
    if isinstance(preferences, dict) and preferences.get("enabled", True) is False:
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
