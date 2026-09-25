from datetime import datetime
import hashlib

import pytest

from sqlalchemy import create_engine, select, func, text
from sqlalchemy.engine import URL

from database import Base
from models import Meeting, MeetingStatus, Segment, Speaker
from scripts.migrate_to_sqlite import _copy_database


def test_migration_copies_tables_and_verifies_segment_text(tmp_path):
    source_path = tmp_path / "source.db"
    target_path = tmp_path / "target.db"
    source_engine = create_engine(URL.create("sqlite", database=str(source_path)))
    Base.metadata.create_all(source_engine)

    with source_engine.begin() as connection:
        meeting = Meeting(
            id="meeting-1", title="Migration check", status=MeetingStatus.COMPLETED,
            created_at=datetime(2026, 1, 1),
        )
        connection.execute(Meeting.__table__.insert(), {
            "id": meeting.id,
            "title": meeting.title,
            "status": meeting.status,
            "created_at": meeting.created_at,
        })
        connection.execute(Speaker.__table__.insert(), {
            "id": "speaker-1",
            "meeting_id": meeting.id,
            "label": "SPEAKER_00",
            "display_name": "Abner",
        })
        connection.execute(Segment.__table__.insert(), [
            {
                "id": "segment-1", "meeting_id": meeting.id, "speaker_id": "speaker-1",
                "start_time": 0.0, "end_time": 1.0, "text": "Reunião começa",
                "order": 0, "is_edited": False,
            },
            {
                "id": "segment-2", "meeting_id": meeting.id, "speaker_id": "speaker-1",
                "start_time": 1.0, "end_time": 2.0, "text": "Garrah confirma",
                "order": 1, "is_edited": True,
            },
        ])

    summary = _copy_database(
        str(URL.create("sqlite", database=str(source_path))), target_path
    )

    assert summary["row_counts"]["meetings"] == 1
    assert summary["row_counts"]["segments"] == 2
    assert len(summary["segment_checksums"]["meeting-1"]) == 64
    target_engine = create_engine(URL.create("sqlite", database=str(target_path)))
    with target_engine.connect() as connection:
        copied = connection.execute(
            select(Segment.__table__.c.text).order_by(Segment.__table__.c.order)
        ).scalars().all()
        fts_matches = connection.execute(text(
            "SELECT COUNT(*) FROM segments_fts WHERE segments_fts MATCH 'reuniao'"
        )).scalar_one()
    assert copied == ["Reunião começa", "Garrah confirma"]
    assert fts_matches == 1
    assert target_path.exists()
    target_hash = hashlib.sha256(target_path.read_bytes()).hexdigest()
    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        _copy_database(str(URL.create("sqlite", database=str(source_path))), target_path)
    assert hashlib.sha256(target_path.read_bytes()).hexdigest() == target_hash
    with source_engine.connect() as connection:
        assert connection.execute(select(func.count()).select_from(Segment.__table__)).scalar_one() == 2
    source_engine.dispose()
    target_engine.dispose()
