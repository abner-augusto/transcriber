import json

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
        assert connection.execute(text("SELECT COUNT(*) FROM schema_migrations")).scalar_one() == 8
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


def test_migration_2_adds_speaker_edited_to_an_existing_segments_table(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE segments (id TEXT PRIMARY KEY, text TEXT NOT NULL)"
        )
        connection.exec_driver_sql("CREATE TABLE meetings (id TEXT PRIMARY KEY)")

    upgrade(engine)
    upgrade(engine)

    with engine.connect() as connection:
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(segments)")}
        assert "speaker_edited" in columns
        assert connection.execute(text("SELECT COUNT(*) FROM schema_migrations")).scalar_one() == 8
    engine.dispose()


def test_migration_3_adds_split_times_to_an_existing_meetings_table(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE segments (id TEXT PRIMARY KEY, text TEXT NOT NULL)"
        )
        connection.exec_driver_sql("CREATE TABLE meetings (id TEXT PRIMARY KEY)")

    upgrade(engine)
    upgrade(engine)

    with engine.connect() as connection:
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(meetings)")}
        assert "split_times" in columns
        assert connection.execute(text("SELECT COUNT(*) FROM schema_migrations")).scalar_one() == 8
    engine.dispose()


def _database_before_migration_4(tmp_path, corrections_per_segment):
    """A database at schema version 3, holding stored Corrections and learned entries."""
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE segments (id TEXT PRIMARY KEY, text TEXT NOT NULL, corrections JSON)"
        )
        connection.exec_driver_sql("CREATE TABLE meetings (id TEXT PRIMARY KEY)")
        connection.exec_driver_sql(
            "CREATE TABLE vocabulary_entries (id TEXT PRIMARY KEY, term TEXT, misheard_as JSON)"
        )
        for index, corrections in enumerate(corrections_per_segment):
            connection.execute(
                text("INSERT INTO segments VALUES (:id, 'x', :corrections)"),
                {"id": f"s{index}", "corrections": json.dumps(corrections)},
            )
    return engine


def _forms(engine, term):
    with engine.connect() as connection:
        raw = connection.execute(
            text("SELECT misheard_as FROM vocabulary_entries WHERE term = :term"), {"term": term}
        ).scalar_one()
    return json.loads(raw)


def test_migration_4_confirms_the_forms_of_confirmed_corrections(tmp_path):
    def stored(heard, term, confirmed):
        return {"heard": heard, "term": term, "rule": "misheard", "confirmed": confirmed}

    engine = _database_before_migration_4(tmp_path, [
        [stored(" Galo,", "Garrah", True), stored(" Doker", "Docker", False)],
        [stored("Garra", "Garrah", False)],
    ])
    with engine.begin() as connection:
        for term, forms in (
            ("Garrah", [{"form": "galo", "count": 2}, {"form": "Garra", "count": 3}]),
            ("Docker", [{"form": "Doker", "count": 2, "confirmed": False}]),
            ("Revit", None),
        ):
            connection.execute(
                text("INSERT INTO vocabulary_entries VALUES (:id, :term, :forms)"),
                {"id": term, "term": term, "forms": json.dumps(forms)},
            )

    upgrade(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("DELETE FROM schema_migrations WHERE version = 4")
    upgrade(engine)  # an interrupted migration runs again without changing the result

    assert _forms(engine, "Garrah") == [
        {"form": "galo", "count": 2, "confirmed": True},
        {"form": "Garra", "count": 3},
    ]
    assert _forms(engine, "Docker") == [{"form": "Doker", "count": 2, "confirmed": False}]
    assert _forms(engine, "Revit") is None
    engine.dispose()


def _meetings_before_migration_5(tmp_path, rows):
    """Version-4 databases with Meetings whose audio files were deleted by hand."""
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE segments (id TEXT PRIMARY KEY, text TEXT NOT NULL)")
        connection.exec_driver_sql(
            "CREATE TABLE meetings (id TEXT PRIMARY KEY, audio_filepath TEXT, "
            "mic_audio_filepath TEXT, system_audio_filepath TEXT)"
        )
        for row in rows:
            connection.execute(text("INSERT INTO meetings VALUES (:id, :a, :m, :s)"), row)
        connection.exec_driver_sql(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, "
            "applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        for version in (1, 2, 3, 4):
            connection.exec_driver_sql(
                f"INSERT INTO schema_migrations(version, name) VALUES ({version}, 'earlier')"
            )
    return engine


def _audio_columns(engine):
    with engine.connect() as connection:
        return {
            row[0]: tuple(row[1:])
            for row in connection.exec_driver_sql(
                "SELECT id, audio_filepath, mic_audio_filepath, system_audio_filepath FROM meetings"
            )
        }


def test_migration_5_points_audio_columns_at_what_is_kept(tmp_path):
    kept = tmp_path / "kept"
    kept.mkdir()
    (kept / "audio.wav").write_bytes(b"RIFF")
    (kept / "mic_source.wav").write_bytes(b"RIFF")
    (kept / "system_source.wav").write_bytes(b"RIFF")
    cleaned = tmp_path / "cleaned"  # the manual cleanup left only audio.wav here
    cleaned.mkdir()
    (cleaned / "audio.wav").write_bytes(b"RIFF")
    empty = tmp_path / "empty"
    empty.mkdir()
    unmounted = tmp_path / "unmounted"  # folder absent: the files cannot be judged
    rows = [
        # processed and cleaned by hand: sources gone, the mix kept
        {"id": "dual", "a": str(cleaned / "audio.wav"),
         "m": str(cleaned / "mic_source.wav"), "s": str(cleaned / "system_source.wav")},
        # a single-track Meeting whose row still names the deleted original
        {"id": "single", "a": str(cleaned / "original.mov"), "m": None, "s": None},
        # nothing left at all
        {"id": "nothing", "a": str(empty / "audio.wav"), "m": str(empty / "m.wav"), "s": None},
        # sources still there: untouched
        {"id": "intact", "a": str(kept / "audio.wav"), "m": str(kept / "mic_source.wav"),
         "s": str(kept / "system_source.wav")},
        {"id": "unmounted", "a": str(unmounted / "audio.wav"), "m": str(unmounted / "m.wav"), "s": None},
    ]
    engine = _meetings_before_migration_5(tmp_path, rows)

    upgrade(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("DELETE FROM schema_migrations WHERE version = 5")
    upgrade(engine)  # an interrupted migration runs again without changing the result

    assert _audio_columns(engine) == {
        "dual": (str(cleaned / "audio.wav"), None, None),
        "single": (str(cleaned / "audio.wav"), None, None),
        "nothing": (None, None, None),
        "intact": (str(kept / "audio.wav"), str(kept / "mic_source.wav"), str(kept / "system_source.wav")),
        "unmounted": (str(unmounted / "audio.wav"), str(unmounted / "m.wav"), None),
    }
    engine.dispose()


def test_migration_5_leaves_a_database_without_audio_columns_alone(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'older.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE segments (id TEXT PRIMARY KEY, text TEXT NOT NULL)")
        connection.exec_driver_sql("CREATE TABLE meetings (id TEXT PRIMARY KEY)")

    upgrade(engine)

    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM schema_migrations")).scalar_one() == 8
    engine.dispose()


def test_migration_6_adds_source_refs_and_guesses_nothing(tmp_path):
    engine = _meetings_before_migration_5(tmp_path, [
        {"id": "old", "a": None, "m": None, "s": None},
    ])

    upgrade(engine)
    upgrade(engine)

    with engine.connect() as connection:
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(meetings)")}
        assert "source_refs" in columns
        assert connection.execute(text("SELECT source_refs FROM meetings")).scalar_one() is None
    engine.dispose()


def test_migration_7_adds_track_layout_and_guesses_nothing(tmp_path):
    engine = _meetings_before_migration_5(tmp_path, [
        {"id": "old", "a": None, "m": None, "s": None},
    ])

    upgrade(engine)
    upgrade(engine)

    with engine.connect() as connection:
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(meetings)")}
        assert "track_layout" in columns
        assert connection.execute(text("SELECT track_layout FROM meetings")).scalar_one() is None
    engine.dispose()


def test_migration_8_adds_cancel_requested_at_to_existing_jobs(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'jobs.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE segments (id TEXT PRIMARY KEY, text TEXT NOT NULL)")
        connection.exec_driver_sql("CREATE TABLE meetings (id TEXT PRIMARY KEY)")
        connection.exec_driver_sql(
            "CREATE TABLE jobs (id TEXT PRIMARY KEY, status VARCHAR(9) NOT NULL)"
        )
        connection.exec_driver_sql("INSERT INTO jobs VALUES ('old', 'PENDING')")

    upgrade(engine)
    upgrade(engine)

    with engine.connect() as connection:
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(jobs)")}
        assert "cancel_requested_at" in columns
        assert connection.execute(text("SELECT cancel_requested_at FROM jobs")).scalar_one() is None
        # CANCELLED fits the column the Enum created for the longest older name (COMPLETED).
        connection.exec_driver_sql("UPDATE jobs SET status = 'CANCELLED'")
        assert connection.execute(text("SELECT status FROM jobs")).scalar_one() == "CANCELLED"
    engine.dispose()
