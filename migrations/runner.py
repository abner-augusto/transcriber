"""Numbered SQLite schema migrations; model metadata is the initial baseline."""

import json
import os

from sqlalchemy import text


def _add_column(table: str, column: str, ddl: str):
    """An idempotent ADD COLUMN: SQLite has no IF NOT EXISTS for columns."""
    def apply(connection):
        existing = {row[1] for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")}
        if column not in existing:
            connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
    return apply


def _confirm_forms_of_confirmed_corrections(connection):
    """Mark a learned Misheard Form confirmed when a stored Correction of it was confirmed.

    Before forms carried their own flag, confirming a Correction was recorded only on
    the Segment. Idempotent; a database without these tables or columns is left alone.
    """
    from transcript.vocabulary_correction import normalize_vocabulary_text

    tables = {row[0] for row in connection.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    )}
    if not {"segments", "vocabulary_entries"} <= tables:
        return
    columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(segments)")}
    if "corrections" not in columns:
        return

    confirmed: set[tuple[str, str]] = set()
    for (raw,) in connection.exec_driver_sql("SELECT corrections FROM segments"):
        for item in (json.loads(raw) if raw else None) or []:
            if isinstance(item, dict) and item.get("confirmed") is True:
                confirmed.add((
                    normalize_vocabulary_text(item.get("heard", "")),
                    normalize_vocabulary_text(item.get("term", "")),
                ))

    for entry_id, term, raw in connection.exec_driver_sql(
        "SELECT id, term, misheard_as FROM vocabulary_entries"
    ).fetchall():
        forms = json.loads(raw) if raw else None
        if not isinstance(forms, list):
            continue
        changed = False
        for form in forms:
            if (
                isinstance(form, dict)
                and form.get("confirmed") is not True
                and (normalize_vocabulary_text(form.get("form", "")), normalize_vocabulary_text(term))
                in confirmed
            ):
                form["confirmed"] = True
                changed = True
        if changed:
            connection.execute(
                text("UPDATE vocabulary_entries SET misheard_as = :forms WHERE id = :id"),
                {"forms": json.dumps(forms), "id": entry_id},
            )


def _audio_paths_of_deleted_files(connection):
    """Make a Meeting's audio columns point at files that exist (plan 045).

    The app keeps only ``audio.wav`` once a Meeting is processed, and a manual cleanup
    deleted the sources of older Meetings without touching their rows. A mic or system
    path whose file is gone becomes NULL. An ``audio_filepath`` whose file is gone moves to
    the ``audio.wav`` beside it, or becomes NULL when that is gone too. A path is judged
    only when its folder exists: without the folder, the files cannot be told from an
    unmounted disk or another working directory, and the row is left alone.
    Changes rows only, never files. Idempotent; a database without these columns is left
    alone.
    """
    tables = {row[0] for row in connection.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    )}
    if "meetings" not in tables:
        return
    columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(meetings)")}
    if not {"audio_filepath", "mic_audio_filepath", "system_audio_filepath"} <= columns:
        return

    def gone(path):
        return bool(path) and not os.path.exists(path) and os.path.isdir(os.path.dirname(path))

    for meeting_id, audio, mic, system in connection.exec_driver_sql(
        "SELECT id, audio_filepath, mic_audio_filepath, system_audio_filepath FROM meetings"
    ).fetchall():
        values = {}
        if gone(audio):
            kept = os.path.join(os.path.dirname(audio), "audio.wav")
            values["audio_filepath"] = kept if os.path.exists(kept) else None
        if gone(mic):
            values["mic_audio_filepath"] = None
        if gone(system):
            values["system_audio_filepath"] = None
        if values:
            assignments = ", ".join(f"{column} = :{column}" for column in values)
            connection.execute(
                text(f"UPDATE meetings SET {assignments} WHERE id = :id"),
                {**values, "id": meeting_id},
            )


# Segment search indexes the implicit rowid of ``segments``, whose primary key is
# TEXT. SQLite documents that VACUUM *may* renumber such rowids; SQLite 3.50
# preserves them (checked 2026-09-25, including VACUUM INTO). If search ever
# returns the wrong Segments after a VACUUM or an external tool rewrote the file,
# run: INSERT INTO segments_fts(segments_fts) VALUES ('rebuild');
_MIGRATIONS = (
    (
        1,
        "segment FTS5 search",
        (
            """CREATE VIRTUAL TABLE IF NOT EXISTS segments_fts USING fts5(
                text,
                content='segments',
                content_rowid='rowid',
                tokenize='unicode61 remove_diacritics 2'
            )""",
            """CREATE TRIGGER IF NOT EXISTS segments_fts_insert AFTER INSERT ON segments
            BEGIN
                INSERT INTO segments_fts(rowid, text) VALUES (new.rowid, new.text);
            END""",
            """CREATE TRIGGER IF NOT EXISTS segments_fts_delete AFTER DELETE ON segments
            BEGIN
                INSERT INTO segments_fts(segments_fts, rowid, text)
                VALUES ('delete', old.rowid, old.text);
            END""",
            """CREATE TRIGGER IF NOT EXISTS segments_fts_update AFTER UPDATE OF text ON segments
            BEGIN
                INSERT INTO segments_fts(segments_fts, rowid, text)
                VALUES ('delete', old.rowid, old.text);
                INSERT INTO segments_fts(rowid, text) VALUES (new.rowid, new.text);
            END""",
            "INSERT INTO segments_fts(segments_fts) VALUES ('rebuild')",
        ),
    ),
    (
        2,
        "segment speaker_edited",
        (_add_column("segments", "speaker_edited", "BOOLEAN NOT NULL DEFAULT 0"),),
    ),
    (
        3,
        "meeting split_times",
        (_add_column("meetings", "split_times", "JSON"),),
    ),
    (
        4,
        "confirmed Misheard Forms from confirmed Corrections",
        (_confirm_forms_of_confirmed_corrections,),
    ),
    (
        5,
        "audio paths of deleted files",
        (_audio_paths_of_deleted_files,),
    ),
)


def upgrade(engine) -> None:
    """Apply each unapplied migration in order and record it.

    pysqlite runs DDL outside the surrounding transaction, so a migration is not
    atomic. Every statement is idempotent instead: a migration interrupted before
    it is recorded is simply applied again on the next start.
    """
    if engine.dialect.name != "sqlite":
        raise RuntimeError("Numbered schema migrations currently support SQLite only")

    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL "
            "DEFAULT CURRENT_TIMESTAMP)"
        ))
        applied = {
            row[0]
            for row in connection.execute(text("SELECT version FROM schema_migrations"))
        }
        for version, name, statements in _MIGRATIONS:
            if version in applied:
                continue
            for statement in statements:
                if callable(statement):
                    statement(connection)
                else:
                    connection.exec_driver_sql(statement)
            connection.execute(
                text("INSERT INTO schema_migrations(version, name) VALUES (:version, :name)"),
                {"version": version, "name": name},
            )
