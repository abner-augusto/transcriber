# Historical PostgreSQL migrations

These SQL files document manual PostgreSQL migrations that predate the
SQLite schema runner. They are retained for audit and recovery reference only;
the application does not execute them. Do not apply them automatically as
part of the PostgreSQL-to-SQLite copy. The importer stops on a schema mismatch
so the source can be reviewed without altering it.
