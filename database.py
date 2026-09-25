import shutil

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.engine import make_url

from config import settings


def configure_sqlite_engine(sqlite_engine):
    """Apply connection-local SQLite settings required by the application."""
    @event.listens_for(sqlite_engine, "connect")
    def _configure_sqlite(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

_database_url = make_url(settings.database_url)
if _database_url.get_backend_name() == "sqlite":
    if _database_url.database not in (None, ":memory:"):
        from pathlib import Path

        Path(_database_url.database).expanduser().resolve().parent.mkdir(
            parents=True, exist_ok=True
        )
    engine = create_engine(
        _database_url,
        connect_args={"check_same_thread": False},
    )
    configure_sqlite_engine(engine)
else:
    # Kept so the one-shot migration command can import the model metadata while
    # the user's existing .env still points at PostgreSQL. The application itself
    # refuses to start against a non-SQLite database in init_db().
    engine = create_engine(_database_url, pool_pre_ping=True)
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
    if engine.dialect.name != "sqlite":
        raise RuntimeError(
            "The application now uses SQLite. Migrate PostgreSQL with "
            "scripts.migrate_to_sqlite and update DATABASE_URL."
        )
    Base.metadata.create_all(bind=engine)
    from migrations.runner import upgrade

    upgrade(engine)


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
