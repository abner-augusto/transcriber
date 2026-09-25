from datetime import datetime
import hashlib
from pathlib import Path
import subprocess
import sys

from sqlalchemy import create_engine, select, func, text
from sqlalchemy.engine import URL

from database import Base
from models import Meeting, MeetingStatus, Segment, Speaker, Job, VocabularyEntry
from models.job import JobStatus, JobType


REPO_ROOT = Path(__file__).resolve().parent.parent


def _migrate(source_url: str, target_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "scripts.migrate_to_sqlite", "--from", source_url, "--to", str(target_path)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _legacy_source(source_path: Path):
    """A database shaped like the last PostgreSQL release, before plans 014–020.

    It still carries the Celery task id on every Job and lacks the columns added
    since (RunConfig, Segment corrections, Misheard Forms).
    """
    source_engine = create_engine(URL.create("sqlite", database=str(source_path)))
    Base.metadata.create_all(source_engine)
    with source_engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE jobs DROP COLUMN run_config")
        connection.exec_driver_sql("ALTER TABLE segments DROP COLUMN corrections")
        connection.exec_driver_sql("ALTER TABLE vocabulary_entries DROP COLUMN misheard_as")
        connection.exec_driver_sql("ALTER TABLE jobs ADD COLUMN celery_task_id VARCHAR")
        connection.execute(Meeting.__table__.insert(), {
            "id": "meeting-1",
            "title": "Migration check",
            "status": MeetingStatus.COMPLETED,
            "created_at": datetime(2026, 1, 1),
        })
        connection.execute(Speaker.__table__.insert(), {
            "id": "speaker-1",
            "meeting_id": "meeting-1",
            "label": "SPEAKER_00",
            "display_name": "Abner",
        })
        connection.execute(Job.__table__.insert(), {
            "id": "job-1", "meeting_id": "meeting-1",
            "job_type": JobType.PROCESS_MEETING, "status": JobStatus.COMPLETED,
        })
        connection.exec_driver_sql(
            "UPDATE jobs SET celery_task_id = 'celery-abc' WHERE id = 'job-1'"
        )
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
                ("segment-1", "meeting-1", "speaker-1", 0.0, 1.0, "Reunião começa", 0, False),
                ("segment-2", "meeting-1", "speaker-1", 1.0, 2.0, "Garrah confirma", 1, True),
            ],
        )
    return source_engine


def test_migration_command_copies_a_legacy_database(tmp_path):
    source_path = tmp_path / "source.db"
    target_path = tmp_path / "target.db"
    source_engine = _legacy_source(source_path)
    source_url = str(URL.create("sqlite", database=str(source_path)))

    result = _migrate(source_url, target_path)

    assert result.returncode == 0, result.stderr
    assert "segments: 2" in result.stdout
    assert "jobs.celery_task_id" in result.stdout
    expected_checksum = hashlib.sha256()
    for order, segment_text in enumerate(["Reunião começa", "Garrah confirma"]):
        payload = f"{order}\0{segment_text}".encode("utf-8")
        expected_checksum.update(len(payload).to_bytes(8, "big"))
        expected_checksum.update(payload)
    assert f"meeting-1: {expected_checksum.hexdigest()}" in result.stdout

    target_engine = create_engine(URL.create("sqlite", database=str(target_path)))
    with target_engine.connect() as connection:
        copied = connection.execute(
            select(Segment.__table__.c.text).order_by(Segment.__table__.c.order)
        ).scalars().all()
        fts_matches = connection.execute(text(
            "SELECT COUNT(*) FROM segments_fts WHERE segments_fts MATCH 'reuniao'"
        )).scalar_one()
        new_columns_are_sql_null = (
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
        vocabulary = connection.execute(select(VocabularyEntry.term)).scalars().all()
    target_engine.dispose()
    assert copied == ["Reunião começa", "Garrah confirma"]
    assert fts_matches == 1
    assert new_columns_are_sql_null == (1, 1, 1)
    assert vocabulary == ["Garrah"]

    target_hash = hashlib.sha256(target_path.read_bytes()).hexdigest()
    rerun = _migrate(source_url, target_path)
    assert rerun.returncode != 0
    assert "Refusing to overwrite" in rerun.stderr
    assert hashlib.sha256(target_path.read_bytes()).hexdigest() == target_hash
    with source_engine.connect() as connection:
        assert connection.execute(select(func.count()).select_from(Segment.__table__)).scalar_one() == 2
    source_engine.dispose()


def test_migration_command_refuses_an_unknown_source_column(tmp_path):
    source_path = tmp_path / "source.db"
    target_path = tmp_path / "target.db"
    source_engine = create_engine(URL.create("sqlite", database=str(source_path)))
    Base.metadata.create_all(source_engine)
    with source_engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE meetings ADD COLUMN notes VARCHAR")
    source_engine.dispose()

    result = _migrate(str(URL.create("sqlite", database=str(source_path))), target_path)

    assert result.returncode != 0
    assert "source-only=['notes']" in result.stderr
    assert not target_path.exists()
    assert not target_path.with_name(target_path.name + ".migrating").exists()
