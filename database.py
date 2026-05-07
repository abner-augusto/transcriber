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
    # Add new enum values BEFORE create_all (so the enum type exists with all values)
    with engine.connect() as conn:
        # Add new MeetingStatus enum values
        for val in ("RECORDING", "FINALIZING"):
            try:
                conn.execute(text(
                    f"ALTER TYPE meetingstatus ADD VALUE IF NOT EXISTS '{val}'"
                ))
            except Exception as e:
                log.debug(f"Enum value meetingstatus.{val}: {e}")

        # Add new JobType enum values
        for val in ("POLISH_PASS", "FINALIZE_LIVE", "REDIARIZE", "REIDENTIFY", "EXTRACT_INSIGHTS"):
            try:
                conn.execute(text(
                    f"ALTER TYPE jobtype ADD VALUE IF NOT EXISTS '{val}'"
                ))
            except Exception as e:
                log.debug(f"Enum value jobtype.{val}: {e}")

        conn.commit()

    Base.metadata.create_all(bind=engine)

    # Add new columns for live mode (safe to re-run)
    migrations = [
        "ALTER TABLE meetings ADD COLUMN IF NOT EXISTS mode VARCHAR DEFAULT 'upload'",
        "ALTER TABLE meetings ADD COLUMN IF NOT EXISTS recording_status VARCHAR",
        "ALTER TABLE meetings ADD COLUMN IF NOT EXISTS polish_history JSON",
        "ALTER TABLE meetings ADD COLUMN IF NOT EXISTS is_encrypted BOOLEAN DEFAULT FALSE",
        "ALTER TABLE meetings ADD COLUMN IF NOT EXISTS encryption_salt TEXT",
        "ALTER TABLE meetings ADD COLUMN IF NOT EXISTS encryption_verify TEXT",
        "ALTER TABLE action_results ADD COLUMN IF NOT EXISTS is_encrypted BOOLEAN DEFAULT FALSE",
        "ALTER TABLE meetings ADD COLUMN IF NOT EXISTS vocabulary TEXT",
        # Full-text search index on segment text
        "CREATE INDEX IF NOT EXISTS ix_segments_text_search ON segments USING gin (to_tsvector('simple', text))",
        "ALTER TABLE meetings ADD COLUMN IF NOT EXISTS protocol_text TEXT",
        "ALTER TABLE segments ADD COLUMN IF NOT EXISTS confidence FLOAT",
    ]
    with engine.connect() as conn:
        for sql in migrations:
            try:
                conn.execute(text(sql))
            except Exception as e:
                log.debug(f"Migration skipped: {sql[:60]}... ({e})")
        conn.commit()


def recover_stale_jobs():
    """Mark any jobs stuck in RUNNING/PENDING as FAILED on startup.

    If the server restarts while a Celery task was running, the job
    status is stuck. This cleans them up so the user can retry.
    """
    from models.job import Job, JobStatus
    from models import Meeting, MeetingStatus

    db = SessionLocal()
    try:
        stale_jobs = db.query(Job).filter(
            Job.status.in_([JobStatus.RUNNING, JobStatus.PENDING])
        ).all()
        for job in stale_jobs:
            job.status = JobStatus.FAILED
            job.error = "Task interrupted by server restart. Please retry."
            job.completed_at = datetime.utcnow()
            # Also reset the meeting status if it was stuck in PROCESSING/FINALIZING
            meeting = db.query(Meeting).filter(Meeting.id == job.meeting_id).first()
            if meeting and meeting.status in (MeetingStatus.PROCESSING, MeetingStatus.FINALIZING):
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


def seed_default_actions():
    """Create default actions if none exist, and migrate existing Swedish ones to English."""
    from models.action import Action

    db = SessionLocal()
    try:
        # Migration: Rename existing Swedish actions to English
        translations = {
            "Sammanfattning": ("Summary", (
                "You are a meeting assistant. Write a clear and concise summary of the meeting. "
                "Include: main topics discussed, key decisions made, "
                "and any unresolved questions. Write in English."
            )),
            "Atgardslista": ("Action Items", (
                "You are a meeting assistant. Create a structured list of action items from the meeting. "
                "For each item, specify:\n"
                "- What needs to be done\n"
                "- Who is responsible (if specified)\n"
                "- Deadline (if mentioned)\n\n"
                "Format as a numbered list. Write in English."
            )),
            "Avidentifierad version": ("Anonymized Version", (
                "You are a privacy specialist. Rewrite the transcription so that all "
                "personal names are replaced with 'Person A', 'Person B', 'Person C', etc. "
                "Also replace organization names, locations, and other identifying details "
                "with generic terms. Keep the content intact. Write in English."
            ))
        }

        for old_name, (new_name, new_prompt) in translations.items():
            action = db.query(Action).filter(Action.name == old_name).first()
            if action:
                log.info(f"Migrating action '{old_name}' to '{new_name}'")
                action.name = new_name
                # Only update prompt if it looks like the default Swedish one (contains 'svenska')
                if "svenska" in action.prompt.lower():
                    action.prompt = new_prompt
        db.commit()

        if db.query(Action).count() > 0:
            return

        defaults = [
            Action(
                name="Summary",
                prompt=(
                    "You are a meeting assistant. Write a clear and concise summary of the meeting. "
                    "Include: main topics discussed, key decisions made, "
                    "and any unresolved questions. Write in English."
                ),
                is_default=True,
            ),
            Action(
                name="Action Items",
                prompt=(
                    "You are a meeting assistant. Create a structured list of action items from the meeting. "
                    "For each item, specify:\n"
                    "- What needs to be done\n"
                    "- Who is responsible (if specified)\n"
                    "- Deadline (if mentioned)\n\n"
                    "Format as a numbered list. Write in English."
                ),
                is_default=True,
            ),
            Action(
                name="Anonymized Version",
                prompt=(
                    "You are a privacy specialist. Rewrite the transcription so that all "
                    "personal names are replaced with 'Person A', 'Person B', 'Person C', etc. "
                    "Also replace organization names, locations, and other identifying details "
                    "with generic terms. Keep the content intact. Write in English."
                ),
                is_default=True,
            ),
        ]

        for action in defaults:
            db.add(action)
        db.commit()
    finally:
        db.close()
