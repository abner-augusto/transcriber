"""Numbered SQLite schema migrations; model metadata is the initial baseline."""

from sqlalchemy import text


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
)


def upgrade(engine) -> None:
    """Apply each unapplied migration in order, recording it transactionally."""
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
                connection.exec_driver_sql(statement)
            connection.execute(
                text("INSERT INTO schema_migrations(version, name) VALUES (:version, :name)"),
                {"version": version, "name": name},
            )
