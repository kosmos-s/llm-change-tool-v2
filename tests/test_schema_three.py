import json

from conftest import synthetic

from llm_change_tool.core import projects
from llm_change_tool.core.datasets import import_dataset
from llm_change_tool.core.jobs import RunConfig, create_job, job_info
from llm_change_tool.core.plans import create_plan
from llm_change_tool.core.projects import create_project, open_project
from llm_change_tool.storage import database
from llm_change_tool.storage.store import execute, one, transaction


def test_populated_v2_upgrade_preserves_runs_and_legacy_reviews(tmp_path, monkeypatch):
    with monkeypatch.context() as scope:
        scope.setattr(database, "SCHEMA_VERSION", 2)
        scope.setattr(projects, "SCHEMA_VERSION", 2)
        project = create_project(tmp_path / "legacy", "existing")
        import_dataset(project, synthetic(tmp_path / "dataset"))
        job = create_job(project, create_plan(project), RunConfig())
        with transaction(project) as con:
            frozen = one(con, "SELECT * FROM llm_runs")
            sample = one(con, "SELECT * FROM samples LIMIT 1")
            execute(
                con,
                "INSERT INTO reviews(sample_id,run_id,state,labels,reason,reviewer,result_hash,origin,created_at) VALUES (:sid,:run,'DONE',:labels,'legacy','tester','hash','local','before')",
                sid=sample["id"],
                run=frozen["id"],
                labels=sample["original_labels"],
            )
    upgraded = open_project(project.root)
    assert upgraded.project_id == project.project_id
    backups = list((project.root / "backups").glob("*.sqlite3"))
    assert len(backups) == 1
    with database.connect(backups[0], readonly=True) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 2
        assert con.execute("SELECT reason FROM reviews").fetchone()[0] == "legacy"
    with transaction(upgraded) as con:
        assert one(con, "SELECT * FROM llm_runs") == frozen
        review = one(con, "SELECT * FROM reviews")
        assert review["reason"] == "legacy" and review["reason_en"] is None
        assert json.loads(review["labels"]) == json.loads(sample["original_labels"])
    assert job_info(upgraded, job)["cost_limit"] == 5
