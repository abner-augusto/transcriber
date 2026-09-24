import logging
import shutil
from datetime import datetime

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from config import settings

log = logging.getLogger(__name__)

engine = create_engine(
    settings.database_url,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    pool_pre_ping=True,  # verify connections before use
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)

    migrations = [
        "ALTER TABLE meetings ADD COLUMN IF NOT EXISTS vocabulary TEXT",
        "ALTER TABLE meetings ADD COLUMN IF NOT EXISTS participants TEXT",
        "ALTER TABLE meetings ADD COLUMN IF NOT EXISTS preset_id VARCHAR",
        "ALTER TABLE meetings ADD COLUMN IF NOT EXISTS mic_audio_filepath VARCHAR",
        "ALTER TABLE meetings ADD COLUMN IF NOT EXISTS system_audio_filepath VARCHAR",
        "ALTER TABLE meetings ADD COLUMN IF NOT EXISTS is_dual_track BOOLEAN",
        "ALTER TABLE segments ADD COLUMN IF NOT EXISTS confidence FLOAT",
        # Full-text search index on segment text
        "CREATE INDEX IF NOT EXISTS ix_segments_text_search ON segments USING gin (to_tsvector('simple', text))",
    ]
    with engine.connect() as conn:
        for sql in migrations:
            try:
                conn.execute(text(sql))
            except Exception as e:
                log.debug(f"Migration skipped: {sql[:60]}... ({e})")
        conn.commit()


def recover_stale_jobs():
    """Fail every RUNNING Job; called when the Celery worker starts.

    A Job is RUNNING only while a worker holds it, and this deployment runs a single
    worker, so at worker start every RUNNING Job was interrupted. PENDING Jobs are
    still queued for this worker and are left alone.
    """
    from models.job import Job, JobStatus
    from models import Meeting, MeetingStatus

    db = SessionLocal()
    try:
        stale_jobs = db.query(Job).filter(Job.status == JobStatus.RUNNING).all()
        for job in stale_jobs:
            job.status = JobStatus.FAILED
            job.error = "Job interrupted by worker restart. Please retry."
            job.completed_at = datetime.utcnow()
            # Also reset the meeting status if it was stuck in PROCESSING
            meeting = db.query(Meeting).filter(Meeting.id == job.meeting_id).first()
            if meeting and meeting.status == MeetingStatus.PROCESSING:
                meeting.status = MeetingStatus.FAILED
        if stale_jobs:
            db.commit()
            log.info(f"Recovered {len(stale_jobs)} stale job(s)")
    finally:
        db.close()


def cleanup_orphaned_storage():
    """Remove storage directories for meetings that no longer exist in the DB."""
    from config import get_storage_path
    from models import Meeting

    storage = get_storage_path()
    if not storage.exists():
        return

    db = SessionLocal()
    try:
        meeting_ids = {row[0] for row in db.query(Meeting.id).all()}
        removed = 0
        for d in storage.iterdir():
            if d.is_dir() and d.name not in meeting_ids:
                shutil.rmtree(d, ignore_errors=True)
                removed += 1
        if removed:
            log.info(f"Cleaned up {removed} orphaned storage directory(s)")
    finally:
        db.close()
