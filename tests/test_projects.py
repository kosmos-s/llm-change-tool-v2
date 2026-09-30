import hashlib
import json
import sqlite3
import subprocess
import sys

import pytest

from llm_change_tool.core.projects import (
    DB_NAME,
    backup_project,
    create_project,
    diagnose_project,
    open_project,
)
from llm_change_tool.storage import database


def test_project_reopens_with_same_identity_and_no_network(tmp_path, monkeypatch):
    import socket

    def no_network(*args, **kwargs):
        raise AssertionError("Network access attempted")

    monkeypatch.setattr(socket, "socket", no_network)
    project = create_project(tmp_path / "한글 작업 공간", "건보 검수")
    assert open_project(project.root) == project
    assert diagnose_project(project.root)["integrity"] == "ok"
    with database.connect(project.database) as con:
        assert con.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_existing_source_folder_never_overwritten(tmp_path):
    source = tmp_path / "original"
    source.mkdir()
    original = source / "sample.json"
    payload = b'{"Artifact": false, "unknown": 12}\r\n'
    original.write_bytes(payload)
    with pytest.raises(FileExistsError):
        create_project(source, "test")
    assert original.read_bytes() == payload
    assert list(source.iterdir()) == [original]


def test_missing_open_creates_nothing(tmp_path):
    path = tmp_path / "missing"
    with pytest.raises(database.DatabaseError):
        open_project(path)
    assert not path.exists()


@pytest.mark.parametrize("future", [False, True])
def test_foreign_or_future_db_is_unchanged(tmp_path, future):
    root = tmp_path / "project"
    if future:
        create_project(root, "test")
        with database.connect(root / DB_NAME) as con:
            con.execute("PRAGMA user_version = 999")
    else:
        root.mkdir()
        with sqlite3.connect(root / DB_NAME) as con:
            con.execute("CREATE TABLE unrelated (value TEXT)")
    db = root / DB_NAME
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    with pytest.raises(database.DatabaseError):
        open_project(root)
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before


def test_backup_captures_committed_wal_and_refuses_overwrite(tmp_path):
    project = create_project(tmp_path / "project", "first")
    with database.connect(project.database) as writer:
        writer.execute("UPDATE project SET name = 'updated'")
        writer.commit()
        destination = backup_project(project)
        with database.connect(destination, readonly=True) as backup:
            assert backup.execute("SELECT name FROM project").fetchone()[0] == "updated"
        before = destination.read_bytes()
        with pytest.raises(FileExistsError):
            database.backup_database(project.database, destination)
        assert destination.read_bytes() == before
    restored = tmp_path / "restored"
    restored.mkdir()
    (restored / DB_NAME).write_bytes(destination.read_bytes())
    assert open_project(restored).project_id == project.project_id


def test_migration_is_idempotent_and_failure_rolls_back(tmp_path, monkeypatch):
    project = create_project(tmp_path / "project", "test")
    version = database.SCHEMA_VERSION
    with database.connect(project.database) as con:
        database.migrate(con, timestamp="now")
        assert con.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == version
        monkeypatch.setattr(database, "SCHEMA_VERSION", version + 1)
        monkeypatch.setitem(
            database.MIGRATIONS,
            version + 1,
            (
                "CREATE TABLE should_rollback (id INTEGER)",
                "INVALID SQL",
            ),
        )
        with pytest.raises(sqlite3.OperationalError):
            database.migrate(con, timestamp="now")
        assert con.execute("PRAGMA user_version").fetchone()[0] == version
        assert (
            con.execute("SELECT name FROM sqlite_master WHERE name = 'should_rollback'").fetchone()
            is None
        )


def test_failed_creation_cleans_only_new_folder(tmp_path, monkeypatch):
    import llm_change_tool.core.projects as projects

    def fail(*args, **kwargs):
        raise RuntimeError("injected failure")

    monkeypatch.setattr(projects, "migrate", fail)
    with pytest.raises(RuntimeError):
        create_project(tmp_path / "new", "test")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("name", ["", "  ", "x" * 121])
def test_invalid_name_does_not_create_folder(tmp_path, name):
    with pytest.raises(ValueError):
        create_project(tmp_path / "new", name)
    assert list(tmp_path.iterdir()) == []


def test_worker_protocol_success_and_failure(tmp_path):
    project = create_project(tmp_path / "한글 space", "test")
    command = [sys.executable, "-m", "llm_change_tool.worker", "diagnose", "--project"]
    success = subprocess.run(command + [str(project.root)], capture_output=True, timeout=10)
    assert success.returncode == 0
    response = json.loads(success.stdout)
    assert response["type"] == "completed"
    assert response["result"]["project_id"] == project.project_id
    failure = subprocess.run(command + [str(tmp_path / "missing")], capture_output=True, timeout=10)
    assert failure.returncode == 1
    assert json.loads(failure.stdout)["type"] == "failed"


def test_worker_file_protocol_without_console(tmp_path, monkeypatch):
    import llm_change_tool.worker as worker
    from llm_change_tool.worker import main

    project = create_project(tmp_path / "project", "test")
    output = tmp_path / "response.json"
    monkeypatch.setattr(worker.sys, "stdout", None)
    assert main(["diagnose", "--project", str(project.root), "--output", str(output)]) == 0
    assert json.loads(output.read_text())["type"] == "completed"


def test_actual_schema_one_upgrade_creates_backup(tmp_path, monkeypatch):
    root = tmp_path / "old project"
    root.mkdir()
    with monkeypatch.context() as scope:
        scope.setattr(database, "SCHEMA_VERSION", 1)
        with database.connect(root / DB_NAME, create=True) as con:
            database.migrate(con, timestamp="before", new=True)
            con.execute("INSERT INTO project VALUES (1,'stable-id','legacy','before','0.1.0')")
            con.commit()
    upgraded = open_project(root)
    assert upgraded.project_id == "stable-id"
    assert list((root / "backups").glob("*.sqlite3"))
    with database.connect(upgraded.database) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == database.SCHEMA_VERSION
        assert con.execute("SELECT count(*) FROM samples").fetchone()[0] == 0
