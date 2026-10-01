"""SQLAlchemy Core unit of work; one engine/connection per operation."""

from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import URL
from sqlalchemy.pool import NullPool

from llm_change_tool.core.projects import Project


@contextmanager
def transaction(project: Project):
    if not project.database.is_file():
        raise FileNotFoundError(project.database)
    engine = create_engine(
        URL.create("sqlite+pysqlite", database=str(project.database)), poolclass=NullPool
    )

    @event.listens_for(engine, "connect")
    def configure(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")

    try:
        with engine.connect() as con:
            con.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                yield con
                con.commit()
            except Exception:
                con.rollback()
                raise
    finally:
        engine.dispose()


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
