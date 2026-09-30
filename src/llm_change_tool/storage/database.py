"""Short-lived SQLite connections and transactional, versioned migrations."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from llm_change_tool.storage.schema_v2 import SQL
from llm_change_tool.storage.schema_v3 import SQL as SQL_V3
from llm_change_tool.storage.schema_v4 import SQL as SQL_V4

APPLICATION_ID = 0x4C435432  # LCT2
SCHEMA_VERSION = 4
MIGRATIONS = {
    4: SQL_V4,
    3: SQL_V3,
    2: SQL,
    1: (
        "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)",
        """CREATE TABLE project (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            project_id TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL CHECK (length(trim(name)) > 0),
            created_at TEXT NOT NULL,
            app_version TEXT NOT NULL
        )""",
    ),
}


class DatabaseError(ValueError):
    """A database is invalid or belongs to a different application/version."""


@contextmanager
def connect(path: Path, *, readonly: bool = False, create: bool = False):
    # mode=rw avoids silently creating a missing database on project open.
    mode = "ro" if readonly else ("rwc" if create else "rw")
    con = sqlite3.connect(path.resolve().as_uri() + f"?mode={mode}", uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("PRAGMA busy_timeout = 5000")
        yield con
    finally:
        con.close()


def validate(con: sqlite3.Connection) -> int:
    if con.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
        raise DatabaseError("LLM Change Tool v2 프로젝트 DB가 아닙니다.")
    version = con.execute("PRAGMA user_version").fetchone()[0]
    if not 1 <= version <= SCHEMA_VERSION:
        raise DatabaseError("지원하지 않는 DB 버전입니다. 앱 버전을 확인하세요.")
    history = [r[0] for r in con.execute("SELECT version FROM schema_migrations ORDER BY version")]
    if history != list(range(1, version + 1)):
        raise DatabaseError("DB 마이그레이션 기록이 일치하지 않습니다.")
    return version


def migrate(con: sqlite3.Connection, *, timestamp: str, new: bool = False) -> None:
    """Apply all pending migrations in one transaction; rollback DDL on failure."""
    if new:
        if con.execute("SELECT name FROM sqlite_master").fetchone():
            raise DatabaseError("기존 DB를 초기화할 수 없습니다.")
        version = 0
    else:
        version = validate(con)
    if version == SCHEMA_VERSION:
        return
    con.execute("BEGIN IMMEDIATE")
    try:
        for target in range(version + 1, SCHEMA_VERSION + 1):
            for statement in MIGRATIONS[target]:
                con.execute(statement)
            con.execute("INSERT INTO schema_migrations VALUES (?, ?)", (target, timestamp))
            con.execute(f"PRAGMA user_version = {target}")
        con.execute(f"PRAGMA application_id = {APPLICATION_ID}")
        con.commit()
    except Exception:
        con.rollback()
        raise


def backup_database(source: Path, destination: Path) -> None:
    # Reserve destination exclusively, so a retry never overwrites a backup.
    with destination.open("xb"):
        pass
    try:
        with connect(source, readonly=True) as src, connect(destination) as dst:
            validate(src)
            src.backup(dst)
            if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise DatabaseError("백업 무결성 확인에 실패했습니다.")
    except Exception:
        destination.unlink(missing_ok=True)
        raise
