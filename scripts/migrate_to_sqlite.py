"""Copy an existing database into a new SQLite file without modifying the source."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from sqlalchemy import MetaData, create_engine, func, inspect, null, select
from sqlalchemy.engine import URL

from database import Base, configure_sqlite_engine
import models  # noqa: F401: register every mapped table in Base.metadata
from migrations.runner import upgrade


_OPTIONAL_ADDITIVE_COLUMNS = {
    "jobs": {"run_config"},
    "segments": {"corrections"},
    "vocabulary_entries": {"misheard_as"},
}

# Columns the application dropped on purpose. Their values mean nothing to the
# current schema, so the migration leaves them behind and says so.
_RETIRED_SOURCE_COLUMNS = {
    "jobs": {"celery_task_id"},  # Celery was removed by ADR-0008.
}


def _segment_checksums(connection, segments_table) -> dict[str, str]:
    checksums: dict[str, hashlib._Hash] = {}
    statement = (
        select(
            segments_table.c.meeting_id,
            segments_table.c.order,
            segments_table.c.text,
        )
        .order_by(
            segments_table.c.meeting_id,
            segments_table.c.order,
            segments_table.c.id,
        )
    )
    for row in connection.execute(statement):
        digest = checksums.setdefault(row.meeting_id, hashlib.sha256())
        text_value = row.text or ""
        payload = f"{row.order}\0{text_value}".encode("utf-8")
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return {meeting_id: digest.hexdigest() for meeting_id, digest in checksums.items()}


def _reflect_and_validate_source(source_engine):
    target_names = set(Base.metadata.tables)
    source_names = set(inspect(source_engine).get_table_names())
    if source_names != target_names:
        missing = sorted(target_names - source_names)
        extra = sorted(source_names - target_names)
        raise ValueError(
            "Source schema does not match the current application schema; "
            f"missing tables={missing}, extra tables={extra}. Stop and review."
        )

    source_metadata = MetaData()
    source_metadata.reflect(bind=source_engine, only=sorted(target_names))
    missing_columns: dict[str, set[str]] = {}
    retired_columns: list[str] = []
    for target_table in Base.metadata.sorted_tables:
        source_table = source_metadata.tables[target_table.name]
        source_columns = set(source_table.c.keys())
        target_columns = set(target_table.c.keys())
        retired = source_columns & _RETIRED_SOURCE_COLUMNS.get(target_table.name, set())
        retired_columns += [f"{target_table.name}.{column}" for column in sorted(retired)]
        source_only = source_columns - target_columns - retired
        target_only = target_columns - source_columns
        allowed = _OPTIONAL_ADDITIVE_COLUMNS.get(target_table.name, set())
        if source_only or target_only - allowed:
            raise ValueError(
                f"Column mismatch in {target_table.name}; "
                f"source-only={sorted(source_only)}, "
                f"target-only={sorted(target_only)}. Stop and review; no data was discarded."
            )
        if any(not target_table.c[column].nullable for column in target_only):
            raise ValueError(
                f"New columns in {target_table.name} are not nullable; "
                "the source schema cannot be migrated losslessly."
            )
        if target_only:
            missing_columns[target_table.name] = target_only
    return source_metadata, missing_columns, retired_columns


def _copy_database(source_url: str, target_path: Path) -> dict:
    target_path = target_path.expanduser().resolve()
    partial_path = target_path.with_name(target_path.name + ".migrating")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing target: {target_path}")
    if partial_path.exists():
        raise FileExistsError(
            f"A previous incomplete migration exists at {partial_path}; "
            "inspect it before removing it or choose another target."
        )

    source_engine = create_engine(source_url, pool_pre_ping=True)
    target_engine = None
    counts: dict[str, int] = {}
    try:
        # Validate the complete source schema before creating even the partial
        # destination, so known incompatibilities leave no migration artefact.
        source_metadata, missing_columns, retired_columns = _reflect_and_validate_source(
            source_engine
        )
        target_engine = create_engine(
            URL.create("sqlite", database=str(partial_path)),
            connect_args={"check_same_thread": False},
        )
        configure_sqlite_engine(target_engine)
        Base.metadata.create_all(bind=target_engine)
        upgrade(target_engine)

        with source_engine.connect().execution_options(stream_results=True) as source_conn:
            with target_engine.begin() as target_conn:
                for target_table in Base.metadata.sorted_tables:
                    source_table = source_metadata.tables[target_table.name]
                    copied_columns = [
                        source_table.c[name] for name in target_table.c.keys()
                        if name in source_table.c
                    ]
                    result = source_conn.execution_options(stream_results=True).execute(
                        select(*copied_columns)
                    )
                    copied = 0
                    while rows := result.mappings().fetchmany(500):
                        values = []
                        for row in rows:
                            record = dict(row)
                            for column in missing_columns.get(target_table.name, ()):
                                record[column] = null()
                            values.append(record)
                        target_conn.execute(
                            target_table.insert(),
                            values,
                        )
                        copied += len(rows)
                    counts[target_table.name] = copied

        source_segments = source_metadata.tables["segments"]
        target_segments = Base.metadata.tables["segments"]
        with source_engine.connect() as source_conn, target_engine.connect() as target_conn:
            source_checksums = _segment_checksums(source_conn, source_segments)
            target_checksums = _segment_checksums(target_conn, target_segments)
        if source_checksums != target_checksums:
            raise ValueError(
                "Segment text checksum differs by Meeting; target kept at "
                f"{partial_path}. Do not switch DATABASE_URL."
            )

        with source_engine.connect() as source_conn, target_engine.connect() as connection:
            for table in Base.metadata.sorted_tables:
                expected = source_conn.execute(
                    select(func.count()).select_from(source_metadata.tables[table.name])
                ).scalar_one()
                actual = connection.execute(
                    select(func.count()).select_from(table)
                ).scalar_one()
                if not expected == counts[table.name] == actual:
                    raise ValueError(
                        f"Row count differs for {table.name}: source={expected}, "
                        f"copied={counts[table.name]}, target={actual}. "
                        f"Target kept at {partial_path}. Do not switch DATABASE_URL."
                    )
            foreign_key_errors = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
            if foreign_key_errors:
                raise ValueError(
                    "SQLite foreign-key verification failed; target kept at "
                    f"{partial_path}. Do not switch DATABASE_URL."
                )

        with target_engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
        target_engine.dispose()
        partial_path.replace(target_path)
        return {
            "target": str(target_path),
            "row_counts": counts,
            "segment_checksums": source_checksums,
            "retired_columns": retired_columns,
        }
    finally:
        source_engine.dispose()
        if target_engine is not None:
            target_engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="source_url", required=True, help="source SQLAlchemy URL")
    parser.add_argument("--to", dest="target_path", required=True, type=Path, help="new SQLite file")
    args = parser.parse_args()

    summary = _copy_database(args.source_url, args.target_path)
    print(f"SQLite migration complete: {summary['target']}")
    print("Rows copied by table:")
    for table, count in summary["row_counts"].items():
        print(f"  {table}: {count}")
    if summary["retired_columns"]:
        print("Retired columns left behind: " + ", ".join(summary["retired_columns"]))
    print("Segment text checksums (Meeting ID: SHA-256):")
    for meeting_id, digest in sorted(summary["segment_checksums"].items()):
        print(f"  {meeting_id}: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
