"""Project engines are reused; connections and transactions remain operation-local."""

from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import URL
from sqlalchemy.pool import NullPool

from llm_change_tool.core.projects import Project


@lru_cache(maxsize=16)
def _engine(database):
    engine = create_engine(URL.create("sqlite+pysqlite", database=database), poolclass=NullPool)

    @event.listens_for(engine, "connect")
    def configure(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")

    return engine


@contextmanager
def transaction(project: Project, *, readonly=False):
    if not project.database.is_file():
        raise FileNotFoundError(project.database)
    with _engine(str(project.database.resolve())).connect() as con:
        if readonly:
            con.exec_driver_sql("PRAGMA query_only=ON")
        con.exec_driver_sql("BEGIN" if readonly else "BEGIN IMMEDIATE")
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise


def execute(con, sql, **values):
    return con.execute(text(sql), values)


def rows(con, sql, **values):
    return [dict(r) for r in execute(con, sql, **values).mappings()]


def one(con, sql, **values):
    result = rows(con, sql, **values)
    if not result:
        raise ValueError("Record not found")
    return result[0]


def has_table(con, name):
    return bool(
        rows(con, "SELECT name FROM sqlite_master WHERE type='table' AND name=:name", name=name)
    )
