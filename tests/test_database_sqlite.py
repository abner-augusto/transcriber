from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy import inspect

import database
from database import Base, configure_sqlite_engine
from migrations.runner import upgrade
import models  # noqa: F401: register every mapped table in Base.metadata


def test_fresh_sqlite_database_initializes_without_legacy_database(tmp_path, monkeypatch):
    engine = create_engine(
        URL.create("sqlite", database=str(tmp_path / "app.db")),
        connect_args={"check_same_thread": False},
    )
    configure_sqlite_engine(engine)
    monkeypatch.setattr(database, "engine", engine)
    database.init_db()
    upgrade(engine)

    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA journal_mode")).scalar_one() == "wal"
        assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        assert connection.execute(text("PRAGMA busy_timeout")).scalar_one() == 5000
        assert connection.execute(text("SELECT COUNT(*) FROM schema_migrations")).scalar_one() == 1
    reflected = set(inspect(engine).get_table_names())
    assert set(Base.metadata.tables).issubset(reflected)
    assert {"segments_fts", "segments_fts_data", "segments_fts_idx"}.issubset(reflected)
    assert "schema_migrations" in reflected

    engine.dispose()


def test_orphan_cleanup_preserves_migration_backups(tmp_path, monkeypatch):
    from sqlalchemy.orm import sessionmaker

    storage = tmp_path / "storage"
    backups = storage / "backups"
    orphan = storage / "orphan-meeting"
    backups.mkdir(parents=True)
    orphan.mkdir()
    (backups / "database.dump").write_bytes(b"retained")

    engine = create_engine(URL.create("sqlite", database=str(tmp_path / "cleanup.db")))
    Base.metadata.create_all(engine)
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=engine))
    monkeypatch.setattr("config.get_storage_path", lambda: storage)

    database.cleanup_orphaned_storage()

    assert (backups / "database.dump").read_bytes() == b"retained"
    assert not orphan.exists()
    engine.dispose()
