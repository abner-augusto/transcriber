from datetime import datetime
import hashlib

import pytest

from sqlalchemy import create_engine, select, func, text
from sqlalchemy.engine import URL

from database import Base
from models import Meeting, MeetingStatus, Segment, Speaker, Job, VocabularyEntry
from models.job import JobStatus, JobType
from scripts.migrate_to_sqlite import _copy_database


def test_migration_copies_tables_and_verifies_segment_text(tmp_path):
    source_path = tmp_path / "source.db"
    target_path = tmp_path / "target.db"
    source_engine = create_engine(URL.create("sqlite", database=str(source_path)))
    Base.metadata.create_all(source_engine)

    with source_engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE jobs DROP COLUMN run_config")
        connection.exec_driver_sql("ALTER TABLE segments DROP COLUMN corrections")
        connection.exec_driver_sql("ALTER TABLE vocabulary_entries DROP COLUMN misheard_as")
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
        connection.execute(Job.__table__.insert(), {
            "id": "job-1", "meeting_id": meeting.id,
            "job_type": JobType.PROCESS_MEETING, "status": JobStatus.COMPLETED,
        })
        connection.exec_driver_sql(
            "INSERT INTO vocabulary_entries (id, term, frequency, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("vocabulary-1", "Garrah", 1, "2026-01-01", "2026-01-01"),
        )
        connection.exec_driver_sql(
            'INSERT INTO segments '
            '(id, meeting_id, speaker_id, start_time, end_time, text, "order", is_edited) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            [
                ("segment-1", meeting.id, "speaker-1", 0.0, 1.0, "Reunião começa", 0, False),
                ("segment-2", meeting.id, "speaker-1", 1.0, 2.0, "Garrah confirma", 1, True),
            ],
        )

    summary = _copy_database(
        str(URL.create("sqlite", database=str(source_path))), target_path
    )

    assert summary["row_counts"]["meetings"] == 1
    assert summary["row_counts"]["segments"] == 2
    assert summary["row_counts"]["jobs"] == 1
    assert summary["row_counts"]["vocabulary_entries"] == 1
    assert len(summary["segment_checksums"]["meeting-1"]) == 64
    target_engine = create_engine(URL.create("sqlite", database=str(target_path)))
    with target_engine.connect() as connection:
        copied = connection.execute(
            select(Segment.__table__.c.text).order_by(Segment.__table__.c.order)
        ).scalars().all()
        fts_matches = connection.execute(text(
            "SELECT COUNT(*) FROM segments_fts WHERE segments_fts MATCH 'reuniao'"
        )).scalar_one()
        optional_values = (
            connection.execute(select(Job.run_config).where(Job.id == "job-1")).scalar_one(),
            connection.execute(select(VocabularyEntry.misheard_as).where(
                VocabularyEntry.id == "vocabulary-1"
            )).scalar_one(),
            connection.execute(select(Segment.corrections).where(
                Segment.id == "segment-1"
            )).scalar_one(),
        )
        optional_sql_nulls = (
            connection.execute(text(
                "SELECT run_config IS NULL FROM jobs WHERE id = 'job-1'"
            )).scalar_one(),
            connection.execute(text(
                "SELECT misheard_as IS NULL FROM vocabulary_entries WHERE id = 'vocabulary-1'"
            )).scalar_one(),
            connection.execute(text(
                "SELECT corrections IS NULL FROM segments WHERE id = 'segment-1'"
            )).scalar_one(),
        )
    assert copied == ["Reunião começa", "Garrah confirma"]
    assert fts_matches == 1
    assert optional_values == (None, None, None)
    assert optional_sql_nulls == (1, 1, 1)
    assert target_path.exists()
    target_hash = hashlib.sha256(target_path.read_bytes()).hexdigest()
    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        _copy_database(str(URL.create("sqlite", database=str(source_path))), target_path)
    assert hashlib.sha256(target_path.read_bytes()).hexdigest() == target_hash
    with source_engine.connect() as connection:
        assert connection.execute(select(func.count()).select_from(Segment.__table__)).scalar_one() == 2
    source_engine.dispose()
    target_engine.dispose()
