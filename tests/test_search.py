from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.search import search_segments
from database import Base
from migrations.runner import upgrade
from models import Meeting, MeetingStatus, Segment


@pytest.fixture
def search_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'search.db'}")
    Base.metadata.create_all(engine)
    upgrade(engine)
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _add_meeting(db, title, texts, *, created_at=None):
    meeting = Meeting(
        title=title,
        status=MeetingStatus.COMPLETED,
        created_at=created_at or datetime(2026, 1, 1),
    )
    db.add(meeting)
    db.flush()
    for index, value in enumerate(texts):
        db.add(Segment(
            meeting_id=meeting.id,
            start_time=float(index),
            end_time=float(index + 1),
            text=value,
            order=index,
        ))
    db.commit()
    return meeting


def test_search_ignores_portuguese_diacritics(search_db):
    meeting = _add_meeting(search_db, "Reunião", ["A reunião começou"])

    results = search_segments("reuniao", search_db)

    assert [item["meeting_id"] for item in results] == [meeting.id]
    assert results[0]["segments"][0]["text"] == "A reunião começou"


def test_search_matches_token_prefix(search_db):
    meeting = _add_meeting(search_db, "Vocabulário", ["Garrah Ribeiro confirmou"])

    results = search_segments("garra", search_db)

    assert [item["meeting_id"] for item in results] == [meeting.id]


def test_search_ranks_repeated_match_higher(search_db):
    repeated = _add_meeting(search_db, "Repeated", ["Garrah Garrah reunião"])
    single = _add_meeting(search_db, "Single", ["Garrah trouxe uma reunião"])

    results = search_segments("garrah", search_db)

    assert [item["meeting_id"] for item in results] == [repeated.id, single.id]


def test_search_groups_segments_by_meeting(search_db):
    meeting = _add_meeting(search_db, "Grouped", ["Garrah chegou", "Garrah saiu"])
    _add_meeting(search_db, "Other", ["Garrah também falou"], created_at=datetime(2026, 1, 2))

    results = search_segments("garrah", search_db)

    grouped = next(item for item in results if item["meeting_id"] == meeting.id)
    assert [segment["order"] for segment in grouped["segments"]] == [0, 1]
    assert len(results) == 2


def test_search_ignores_fts_operators_and_returns_empty_for_punctuation(search_db):
    meeting = _add_meeting(search_db, "Safe query", ["AND OR NOT NEAR"])

    results = search_segments('"AND"', search_db)
    empty = search_segments("!!!", search_db)

    assert [item["meeting_id"] for item in results] == [meeting.id]
    assert empty == []


def test_search_index_tracks_segment_updates_and_deletes(search_db):
    meeting = _add_meeting(search_db, "Index updates", ["Garrah chegou"])
    segment = search_db.query(Segment).filter_by(meeting_id=meeting.id).one()

    segment.text = "Reunião começou"
    search_db.commit()
    assert search_segments("garrah", search_db) == []
    assert len(search_segments("reuniao", search_db)) == 1

    search_db.delete(segment)
    search_db.commit()
    assert search_segments("reuniao", search_db) == []
