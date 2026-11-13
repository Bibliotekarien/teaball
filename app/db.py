"""Database access: PRAGMA-correct connections, migrations, view/trigger recreation.

Migrations (db/migrations/NNNN_*.sql) hold tables, indexes and data fixes and are
applied once, tracked in schema_migration. Views and triggers live in
db/views_triggers.sql, which is DROP+CREATE-run on every startup so iterating on
them never needs a migration.
"""

import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from app import config, instans, organisationer

logger = logging.getLogger("teaball.db")

# CTEs inside trigger bodies (the D1 cycle guard) need SQLite >= 3.34.
MIN_SQLITE_VERSION = (3, 34, 0)


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Without a path: the database of the request's organisation
    (app/organisationer.py), which is DB_PATH on a single-organisation
    installation."""
    # check_same_thread=False: each request gets its own connection, but FastAPI
    # may run dependency and endpoint on different threadpool threads.
    if db_path is None and organisationer.flera():
        # A request never creates an organisation's database (they are made on
        # the server): mode=rw fails on a missing file instead of creating an
        # empty one, e.g. when scripts/organisationer.py ta-bort removes it
        # while a request that already chose it is in flight.
        uri = organisationer.aktuell().databas.resolve().as_uri() + "?mode=rw"
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    else:
        path = Path(db_path) if db_path is not None else organisationer.aktuell().databas
        path.parent.mkdir(parents=True, exist_ok=True)
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


def _kopia_fore_migration(conn: sqlite3.Connection, sista_version: int) -> Path | None:
    """Snapshot the database file next to itself before pending migrations run.

    Each migration is atomic, but atomicity does not cover "migrated
    successfully to the wrong result" — this copy does. Taken via the backup
    API (consistent even in WAL mode, same mechanism as scripts/backup.sh).
    Skipped for in-memory databases and for fresh files that hold nothing but
    schema_migration. Restore = stop the app, copy the file back. The copy is
    never rotated: delete it once the upgrade is verified."""
    rad = conn.execute("PRAGMA database_list").fetchone()
    fil = rad["file"] if rad else None
    if not fil:
        return None
    har_data = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table'"
        " AND name != 'schema_migration' LIMIT 1"
    ).fetchone()
    if not har_data:
        return None
    kalla = Path(fil)
    stampel = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    mal = kalla.with_name(f"{kalla.stem}.fore-{sista_version:04d}-{stampel}{kalla.suffix}")
    kopia = sqlite3.connect(mal)
    try:
        conn.backup(kopia)
    finally:
        kopia.close()
    return mal


def migrate(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migration ("
        " version INTEGER PRIMARY KEY,"
        " applied TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    applied = {row["version"] for row in conn.execute("SELECT version FROM schema_migration")}
    vantande = [
        (int(path.name.split("_", 1)[0]), path)
        for path in sorted(config.MIGRATIONS_DIR.glob("[0-9]*.sql"))
        if int(path.name.split("_", 1)[0]) not in applied
    ]
    if not vantande:
        return
    # A failed snapshot aborts the whole startup: better to refuse migrating
    # than to migrate a production database without the promised copy.
    kopia = _kopia_fore_migration(conn, max(v for v, _ in vantande))
    if kopia:
        logger.info("Säkerhetskopia före migration: %s", kopia)
    for version, path in vantande:
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
    instans.fyll_fran_miljon(conn)


def get_conn():
    """FastAPI dependency: one connection per request."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()
