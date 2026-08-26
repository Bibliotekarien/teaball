"""Database access: PRAGMA-correct connections, migrations, view/trigger recreation.

Migrations (db/migrations/NNNN_*.sql) hold tables, indexes and data fixes and are
applied once, tracked in schema_migration. Views and triggers live in
db/views_triggers.sql, which is DROP+CREATE-run on every startup so iterating on
them never needs a migration.
"""

import sqlite3
from pathlib import Path

from app import config

# CTEs inside trigger bodies (the D1 cycle guard) need SQLite >= 3.34.
MIN_SQLITE_VERSION = (3, 34, 0)


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path is not None else config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: each request gets its own connection, but FastAPI
    # may run dependency and endpoint on different threadpool threads.
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def assert_sqlite_version() -> None:
    if sqlite3.sqlite_version_info < MIN_SQLITE_VERSION:
        raise RuntimeError(
            f"SQLite >= {'.'.join(map(str, MIN_SQLITE_VERSION))} required "
            f"(found {sqlite3.sqlite_version}); the cycle-guard trigger needs CTE support."
        )


def migrate(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migration ("
        " version INTEGER PRIMARY KEY,"
        " applied TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    applied = {row["version"] for row in conn.execute("SELECT version FROM schema_migration")}
    for path in sorted(config.MIGRATIONS_DIR.glob("[0-9]*.sql")):
        version = int(path.name.split("_", 1)[0])
        if version in applied:
            continue
        # One atomic transaction per migration, version row included — a failed
        # migration leaves neither partial schema nor a missing version row.
        # Migration files must therefore not contain their own BEGIN/COMMIT.
        conn.executescript(
            "BEGIN;\n"
            + path.read_text(encoding="utf-8")
            + f"\nINSERT INTO schema_migration (version) VALUES ({version});\nCOMMIT;"
        )


def create_views_and_triggers(conn: sqlite3.Connection) -> None:
    conn.executescript(config.VIEWS_TRIGGERS_SQL.read_text(encoding="utf-8"))
    conn.commit()


def init_db(conn: sqlite3.Connection) -> None:
    assert_sqlite_version()
    migrate(conn)
    create_views_and_triggers(conn)


def get_conn():
    """FastAPI dependency: one connection per request."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()
