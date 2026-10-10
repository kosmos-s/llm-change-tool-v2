import json
import shutil
from collections import Counter
from pathlib import Path

import pytest
from conftest import synthetic
from PySide6.QtWidgets import QApplication

from llm_change_tool.core.candidates import prepare_candidates, targets
from llm_change_tool.core.datasets import import_dataset
from llm_change_tool.core.exporting import export_run, final_gate
from llm_change_tool.core.jobs import (
    RunConfig,
    control_job,
    create_job,
    job_info,
    recover_jobs,
    run_job,
)
from llm_change_tool.core.plans import create_plan, preview_plan, validate_plan
from llm_change_tool.core.projects import create_project, open_project
from llm_change_tool.core.reviews import compare_run, save_review
from llm_change_tool.core.sampling import balanced_source_sample, balanced_unique_pilot_sample
from llm_change_tool.providers.base import ProviderFailure
from llm_change_tool.storage.store import execute, one, rows, transaction
from llm_change_tool.ui.components import ResultPanel
from llm_change_tool.ui.window import MainWindow


def clone(root, *, split="train", source="errors"):
    destination = root / source / split / "other_fp_00"
    destination.mkdir(parents=True)
    for path in (root / "errors/train/artifact_fn_00").glob("0000_combined.*"):
        shutil.copyfile(path, destination / path.name)
    return destination / "0000_combined.json"


def change(path, update):
    doc = json.loads(path.read_text(encoding="utf-8"))
    update(doc)
    path.write_text(json.dumps(doc), encoding="utf-8")


def project_for(tmp_path, root):
    project = create_project(tmp_path / "project", "candidate test")
    import_dataset(project, root)
    return project


def test_decoded_duplicates_keep_origins_and_source_bytes(tmp_path):
    root = synthetic(tmp_path / "data")
    path = clone(root, source="dataset")
    image = path.with_suffix(".jpg")
    image.write_bytes(image.read_bytes() + b"different JPEG metadata")
    original = {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    project = project_for(tmp_path, root)
    candidates, inventory = prepare_candidates(project)
    assert len(candidates) == 6 and inventory["duplicate_copies"] == 1
    group = next(g for g in inventory["groups"] if len(g["member_ids"]) == 2)
    assert group["sources"] == ["dataset", "errors"] and group["status"] == "eligible"
    assert group["error_types"] == ["artifact_fn_00"]
    assert any(s["selection_source"] == "dataset+errors" for s in candidates)
    plan = create_plan(project, sample_count=50, candidate_policy=True)
    with transaction(project) as con:
        assert len(validate_plan(con, plan)[1]) == 6
    assert {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()} == original


@pytest.mark.parametrize("kind", ["conflict", "incomplete", "leakage", "conflict_and_leakage"])
def test_held_groups_do_not_globally_block_safe_candidates(tmp_path, kind):
    root = synthetic(tmp_path / "data")
    path = clone(root, split="val" if "leakage" in kind else "train")
    if "conflict" in kind:
        change(path, lambda d: d.update(Tree="o"))
    if kind == "incomplete":
        change(path, lambda d: (d.update(Artifact="o"), d["artifact_detail"].pop("arti_bu")))
    project = project_for(tmp_path, root)
    candidates, inventory = prepare_candidates(project)
    assert len(candidates) == 5 and inventory["held_unique_count"] == 1
    held = next(g for g in inventory["groups"] if g["status"] == "held")
    assert not set(held["member_ids"]) & {s["id"] for s in candidates}
    if kind == "conflict_and_leakage":
        assert set(held["reasons"]) == {"label_conflict", "split_leakage"}
        assert sum(inventory["held_reason_counts"].values()) == 2
    job = create_job(project, create_plan(project, candidate_policy=True), RunConfig())
    assert run_job(project, job)["counts"]["COMPLETED"] == 5


def test_unknown_singleton_kept_for_required_review(tmp_path):
    root = synthetic(tmp_path / "data")
    change(
        next(root.rglob("*.json")),
        lambda d: (d.update(Artifact="o"), d["artifact_detail"].pop("arti_bu")),
    )
    candidates, inventory = prepare_candidates(project_for(tmp_path, root))
    assert len(candidates) == 6 and any(g["review_required"] for g in inventory["groups"])
    assert any(None in json.loads(s["original_labels"]).values() for s in candidates)


@pytest.mark.parametrize("damage", ["json", "missing", "corrupt"])
def test_local_fatal_excludes_only_affected_sample(tmp_path, damage):
    root = synthetic(tmp_path / "data", 3)
    path = next(root.rglob("*.json"))
    if damage == "json":
        path.write_text("{")
    elif damage == "missing":
        path.with_suffix(".jpg").unlink()
    else:
        path.with_suffix(".jpg").write_bytes(b"broken")
    project = project_for(tmp_path, root)
    candidates, inventory = prepare_candidates(project)
    assert len(candidates) == 2 and inventory["registered_count"] == 3
    assert len(inventory["rejected"]) == 1
    assert inventory["rejected"][0]["severity"] == "FATAL"
    assert inventory["rejected"][0]["scope"] == "sample_excluded"
    assert preview_plan(project, sample_count=50, candidate_policy=True)["selected_count"] == 2


def test_shortage_preview_without_partial_production_plan(tmp_path):
    project = project_for(tmp_path, synthetic(tmp_path / "data", 3))
    report = preview_plan(project, "production")
    assert not report["ready"] and report["shortages"] == dict(train=999, val=999, test=999)
    assert report["inventory"]["split_counts"]["train"]["shortage"] == 999
    with pytest.raises(ValueError, match="insufficient unique"):
        create_plan(project, "production")
    with transaction(project) as con:
        assert not rows(con, "SELECT * FROM work_plans")


def test_source_and_policy_tamper_block_while_legacy_plan_is_preserved(imported):
    project, root = imported
    legacy = create_plan(project)
    new = create_plan(project, candidate_policy=True)
    assert legacy != new
    with transaction(project) as con:
        old = rows(con, "SELECT * FROM work_plan_items WHERE plan_id=:id", id=legacy)
        execute(con, "UPDATE plan_selections SET payload='{}' WHERE plan_id=:id", id=new)
        with pytest.raises(ValueError, match="selection policy"):
            validate_plan(con, new)
        assert rows(con, "SELECT * FROM work_plan_items WHERE plan_id=:id", id=legacy) == old
        validate_plan(con, legacy)
    path = next(root.rglob("*.json"))
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="integrity"):
        preview_plan(project, candidate_policy=True)


def test_all_pilot_preview_has_no_unsupported_keyword(imported):
    assert preview_plan(imported[0], sample_count=None)["selected_count"] == 6


def test_source_and_pilot_balance_independent_of_child_group_count():
    samples = [
        dict(
            id=f"{source}-{split}-{n}",
            source=source,
            split=split,
            error_type=f"type-{n}" if source == "errors" else "",
            original_labels='{"arti":0}',
        )
        for source in ("dataset", "errors")
        for split in ("train", "val", "test")
        for n in range(20)
    ]
    selected = balanced_source_sample(samples, 20, "stable")
    assert Counter(s["source"] for s in selected) == {"dataset": 10, "errors": 10}
    assert selected == balanced_source_sample(list(reversed(samples)), 20, "stable")
    pilot = balanced_unique_pilot_sample(samples, 12, "stable")
    assert Counter((s["source"], s["split"]) for s in pilot) == {
        (source, split): 2 for source in ("dataset", "errors") for split in ("train", "val", "test")
    }


@pytest.mark.parametrize(
    "value",
    [
        {"train": 999, "val": 1000, "test": 1000},
        {"train": True, "val": 1000, "test": 1999},
        {"train": 0, "val": 1000, "test": 2000},
    ],
)
def test_invalid_split_targets(value):
    with pytest.raises(ValueError, match="3000"):
        targets(value)


def test_configuration_pauses_once_and_requires_explicit_fix_confirmation(imported):
    project, _ = imported
    job = create_job(project, create_plan(project), RunConfig())

    class BadKey:
        calls = 0

        def predict(self, *args):
            self.calls += 1
            raise ProviderFailure("http_401")

    provider = BadKey()
    info = run_job(project, job, provider=provider)
    assert provider.calls == 1 and info["state"] == "PAUSED"
    assert info["counts"] == {"FAILED": 1, "PENDING": 5} and info["usage"]["reserved"] == 0
    control_job(project, job, "retry")
    assert job_info(project, job)["counts"] == info["counts"]
    with pytest.raises(ValueError, match="확인"):
        control_job(project, job, "retry_configuration")
    control_job(project, job, "retry_configuration", configuration_fixed=True)
    assert run_job(project, job)["state"] == "COMPLETED"


def test_image_failure_has_data_signal_and_cannot_blindly_retry(monkeypatch, imported):
    project, _ = imported
    job = create_job(project, create_plan(project), RunConfig())

    def broken(*args):
        raise ValueError("image decode failed")

    monkeypatch.setattr("llm_change_tool.core.jobs.sample_images", broken)

    class MustNotCall:
        def predict(self, *args):
            raise AssertionError("must not call provider")

    run = run_job(project, job, provider=MustNotCall())["run_id"]
    control_job(project, job, "retry")
    assert job_info(project, job)["counts"] == {"FAILED": 6}
    assert job_info(project, job)["failures"][0]["domain"] == "data"
    compare_run(project, run)
    with transaction(project) as con:
        assert all(
            "data_error" in json.loads(c["signals"]) for c in rows(con, "SELECT * FROM comparisons")
        )
        assert not any(a["reserved_cost"] for a in rows(con, "SELECT * FROM attempts"))


def test_ui_targets_and_shortage_report(imported):
    app = QApplication.instance() or QApplication([])
    project, _ = imported
    window = MainWindow()
    window.set_project(project)
    window.mode.setCurrentIndex(window.mode.findData("production"))
    assert window.production_targets() == dict(train=1000, val=1000, test=1000)
    window.split_targets["train"].setText("1200")
    window.split_targets["test"].setText("800")
    assert window.production_targets()["test"] == 800
    report = preview_plan(project, "production")
    panel = ResultPanel()
    panel.set_result(report)
    assert "부족" in panel.summary.text() and panel.values.rowCount() >= 7
    window.show_selection_preview(report)
    assert "본작업 생성 불가" in window.selection_hint.text()
    window.close()
    panel.close()
    app.processEvents()


def test_content_index_upgrade_and_tamper_detection(imported):
    project, _ = imported
    with transaction(project) as con:
        execute(con, "DELETE FROM sample_contents")
    assert prepare_candidates(open_project(project.root))[1]["eligible_count"] == 6
    plan = create_plan(project, candidate_policy=True)
    with transaction(project) as con:
        execute(con, "UPDATE sample_contents SET content_hash='modified'")
        with pytest.raises(ValueError, match="content index"):
            validate_plan(con, plan)


def test_new_policy_export_contains_selection_and_excluded_scope(tmp_path):
    root = synthetic(tmp_path / "data", 3)
    next(root.rglob("*.json")).write_text("{")
    project = project_for(tmp_path, root)
    job = create_job(project, create_plan(project, candidate_policy=True), RunConfig())
    run = run_job(project, job)["run_id"]
    compare_run(project, run)
    with transaction(project) as con:
        results = rows(con, "SELECT * FROM llm_results WHERE run_id=:id", id=run)
    for result in results:
        save_review(
            project,
            run,
            result["sample_id"],
            json.loads(result["prediction"])["labels"],
            "합성 테스트 이미지 확인",
            "synthetic-test",
            "DONE",
            None,
        )
    assert final_gate(project, run)["passed"]
    exported = export_run(project, run)
    manifest = json.loads((Path(exported["path"]) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["selection"]["selected_count"] == 2
    assert manifest["quality_issues"][0]["scope"] == "sample_excluded"
    assert not manifest["production"]


def test_recovery_unknown_outcome_overrides_old_retryable_metadata(imported):
    project, _ = imported
    job = create_job(project, create_plan(project), RunConfig())
    with transaction(project) as con:
        item = one(con, "SELECT sample_id FROM job_items WHERE job_id=:id LIMIT 1", id=job)
        execute(
            con,
            "UPDATE job_items SET state='RUNNING' WHERE job_id=:job AND sample_id=:sid",
            job=job,
            sid=item["sample_id"],
        )
        execute(
            con,
            "INSERT INTO job_failures VALUES (:job,:sid,'transient','http_503',1)",
            job=job,
            sid=item["sample_id"],
        )
    recover_jobs(project)
    control_job(project, job, "retry")
    assert job_info(project, job)["counts"] == {"FAILED": 1, "PENDING": 5}
    with transaction(project) as con:
        assert one(con, "SELECT * FROM job_failures")["retryable"] == 0


def test_completed_job_stays_completed_after_retry(imported):
    project, _ = imported
    job = create_job(project, create_plan(project), RunConfig())
    run_job(project, job)
    control_job(project, job, "retry")
    assert job_info(project, job)["state"] == "COMPLETED"
