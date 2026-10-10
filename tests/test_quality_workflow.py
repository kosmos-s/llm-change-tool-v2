import json
from pathlib import Path

import pytest
from conftest import synthetic

from llm_change_tool.core.datasets import import_dataset, scan_dataset
from llm_change_tool.core.exporting import final_gate
from llm_change_tool.core.jobs import RunConfig, create_job, run_job
from llm_change_tool.core.labels import KEYS, canonical
from llm_change_tool.core.metrics import create_golden, review_report
from llm_change_tool.core.plans import create_plan
from llm_change_tool.core.projects import create_project, open_project
from llm_change_tool.core.quality import (
    preparation_preview,
    prepare_dataset,
    quality_report,
    set_exclusion,
)
from llm_change_tool.core.reviews import (
    compare_run,
    review_queue,
    save_review,
    select_auto_audit,
    undo_review,
)
from llm_change_tool.core.sampling import balanced_sample, distribution
from llm_change_tool.providers.base import ProviderResponse
from llm_change_tool.storage.store import one, rows, transaction


def prepared(tmp_path, kind=None):
    root = synthetic(tmp_path / "data", 6)
    path = sorted(root.rglob("*.json"))[0]
    if kind in ("unknown", "contradiction"):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if kind == "unknown":
            doc["Artifact"] = "o"
            doc["artifact_detail"].pop("arti_bu")
        else:
            doc["artifact_detail"]["arti_bu"] = "o"
        path.write_text(json.dumps(doc), encoding="utf-8")
    if kind == "duplicate":
        images = sorted(root.rglob("*.jpg"))
        images[1].write_bytes(images[0].read_bytes())
    project = create_project(tmp_path / "project", "quality")
    import_dataset(project, root)
    job = create_job(project, create_plan(project), RunConfig())
    info = run_job(project, job)
    run = info["run_id"]
    compare_run(project, run)
    return project, root, run


def approve(project, run):
    for s in review_queue(project, run):
        save_review(
            project,
            run,
            s["id"],
            dict.fromkeys(KEYS, 0),
            "확인 후 변화 없음",
            "tester",
            expected_revision=s["revision"],
        )


@pytest.mark.parametrize("kind", ["unknown", "contradiction"])
def test_unresolved_draft_deferred_undo_and_gate(tmp_path, kind):
    project, root, run = prepared(tmp_path, kind)
    sample = next(s for s in review_queue(project, run) if "source_labels" in s["signals"])
    labels = json.loads(sample["original_labels"])
    revision = save_review(project, run, sample["id"], labels, "나중에", "tester", "DEFERRED")
    assert not final_gate(project, run)["passed"]
    revision = save_review(
        project, run, sample["id"], dict.fromkeys(KEYS, 0), "확정", "tester", "DONE", revision
    )
    undo_review(project, run, sample["id"], "tester", revision)
    latest = next(s for s in review_queue(project, run) if s["id"] == sample["id"])
    assert latest["review_state"] == "DEFERRED"
    assert json.loads(latest["reviewed_labels"]) == labels
    # Undo through the first review restores the original draft too.
    undo_review(project, run, sample["id"], "tester", latest["revision"])
    latest = next(s for s in review_queue(project, run) if s["id"] == sample["id"])
    assert latest["review_state"] == "DRAFT"
    assert json.loads(latest["reviewed_labels"]) == labels
    assert open_project(project.root).project_id == project.project_id


def test_truncated_jpeg_is_fatal(tmp_path):
    root = synthetic(tmp_path / "data", 3)
    image = next(root.rglob("*.jpg"))
    image.write_bytes(image.read_bytes()[:-30])
    samples, errors, _ = scan_dataset(root)
    assert len(samples) == 2
    assert any("truncated" in e["error"] and e["severity"] == "FATAL" for e in errors)
    project = create_project(tmp_path / "project", "bad")
    import_dataset(project, root)
    for mode in ("pilot", "production"):
        with pytest.raises(ValueError, match="quality"):
            create_plan(project, mode)


def test_prepare_exclusions_are_explicit_audited_and_source_readonly(tmp_path):
    project, root, run = prepared(tmp_path, "duplicate")
    approve(project, run)
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    report = quality_report(project, run)
    assert report["duplicates"]
    assert not preparation_preview(project, run)[0]["ready"]
    sid = report["duplicates"][0][1]["id"]
    set_exclusion(project, run, sid, "동일 이미지 대표본 유지")
    assert preparation_preview(project, run)[0]["ready"]
    result = prepare_dataset(project, run, tmp_path / "prepared")
    assert result["included"] == 5 and result["excluded"] == 1
    assert result["production_size_ready"] is False
    assert scan_dataset(Path(result["path"]))[1] == []
    manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    assert manifest["excluded"][0]["reason"] == "동일 이미지 대표본 유지"
    assert before == {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    set_exclusion(project, run, sid, None)
    assert not preparation_preview(project, run)[0]["ready"]
    with transaction(project) as con:
        assert len(rows(con, "SELECT * FROM quality_events")) == 2


def test_prepare_requires_reviews_and_rechecks_integrity(tmp_path):
    project, root, run = prepared(tmp_path, "unknown")
    with pytest.raises(ValueError, match="차단"):
        prepare_dataset(project, run, tmp_path / "blocked")
    assert not (tmp_path / "blocked").exists()
    approve(project, run)
    result = prepare_dataset(project, run, tmp_path / "good")
    assert not scan_dataset(Path(result["path"]))[1]
    next(root.rglob("*.jpg")).write_bytes(b"changed")
    with pytest.raises(ValueError, match="무결성"):
        prepare_dataset(project, run, tmp_path / "changed")


def test_prepare_atomic_failure(tmp_path, monkeypatch):
    import llm_change_tool.core.quality as quality

    project, _, run = prepared(tmp_path)
    approve(project, run)

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(quality.shutil, "copyfile", fail)
    with pytest.raises(OSError):
        prepare_dataset(project, run, tmp_path / "prepared")
    assert not (tmp_path / "prepared").exists()
    assert not list(tmp_path.glob(".prepare-*"))
    with transaction(project) as con:
        assert not rows(con, "SELECT * FROM preparation_history")


def test_balanced_selection_is_reproducible_and_spreads_strata():
    samples = [
        {
            "id": str(i),
            "split": "train",
            "error_type": "rare" if i < 3 else "common",
            "original_labels": canonical(dict.fromkeys(KEYS, 0)),
        }
        for i in range(100)
    ]
    chosen = balanced_sample(samples, 10, "seed")
    assert chosen == balanced_sample(list(reversed(samples)), 10, "seed")
    assert len({s["id"] for s in chosen}) == 10
    assert sum(s["error_type"] == "rare" for s in chosen) == 3
    assert chosen != balanced_sample(samples, 10, "other")
    assert sum(distribution(chosen).values()) == 10


def test_evaluation_split_and_duplicate_guards(tmp_path):
    project, _, run = prepared(tmp_path, "duplicate")
    approve(project, run)
    with pytest.raises(ValueError):
        create_golden(project, run, "bad", purpose="evaluation", split="train")
    duplicate_split = quality_report(project, run)["duplicates"][0][0]["split"]
    # Same-split duplicates are also forbidden for a formal evaluation set.
    with pytest.raises(ValueError, match="중복"):
        create_golden(project, run, "duplicate", purpose="evaluation", split=duplicate_split)
    golden = create_golden(project, run, "training", purpose="training", split="train")
    assert golden["purpose"] == "training"
    with transaction(project) as con:
        assert one(con, "SELECT * FROM golden_metadata")["split"] == "train"


def test_audit_requires_human_review_and_reports_corrections(tmp_path):
    class Keep:
        def predict(self, *args):
            return ProviderResponse(
                canonical(
                    {
                        "labels": dict.fromkeys(KEYS, 0),
                        "confidence": 0.99,
                        "reason": "동일",
                        "review_required": False,
                    }
                )
            )

    project = create_project(tmp_path / "project", "audit")
    import_dataset(project, synthetic(tmp_path / "data"))
    job = create_job(project, create_plan(project), RunConfig())
    info = run_job(project, job, provider=Keep())
    run = info["run_id"]
    compare_run(project, run)
    assert final_gate(project, run)["passed"]
    assert select_auto_audit(project, run, 2, "fixed")["audit_selected"] == 2
    assert not final_gate(project, run)["passed"]
    audit = [s for s in review_queue(project, run) if "auto_audit" in s["signals"]]
    assert len(audit) == 2
    for i, s in enumerate(audit):
        labels = dict.fromkeys(KEYS, 0)
        labels["tree"] = i
        save_review(project, run, s["id"], labels, "표본 확인", "tester", elapsed_seconds=12)
    compare_run(project, run)
    assert final_gate(project, run)["passed"]
    report = review_report(project, run)
    assert report["auto_audit"]["corrected"] == 1
    assert report["auto_audit"]["observed_error_rate"] == 0.5
    assert report["estimated_interaction_seconds"] == 24


def test_unknown_deferred_package_roundtrip(tmp_path):
    from llm_change_tool.core.exchange import export_reviews, import_reviews
    from llm_change_tool.core.projects import backup_project, restore_project

    project, root, run = prepared(tmp_path, "unknown")
    restored = restore_project(backup_project(project), tmp_path / "restored")
    sample = next(s for s in review_queue(project, run) if "source_labels" in s["signals"])
    save_review(
        project,
        run,
        sample["id"],
        json.loads(sample["original_labels"]),
        "미확정 보류",
        "tester",
        "DEFERRED",
    )
    result = import_reviews(restored, run, export_reviews(project, run)["path"])
    assert result["NEW"] == 1
    restored_sample = next(s for s in review_queue(restored, run) if s["id"] == sample["id"])
    assert json.loads(restored_sample["reviewed_labels"])["arti_bu"] is None


def test_v3_upgrade_keeps_project_and_backup(tmp_path, monkeypatch):
    from llm_change_tool.core import projects
    from llm_change_tool.storage import database

    with monkeypatch.context() as patch:
        patch.setattr(database, "SCHEMA_VERSION", 3)
        patch.setattr(projects, "SCHEMA_VERSION", 3)
        project = create_project(tmp_path / "legacy", "v3")
        import_dataset(project, synthetic(tmp_path / "data"))
        job = create_job(project, create_plan(project), RunConfig())
    upgraded = open_project(project.root)
    with database.connect(upgraded.database) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == database.SCHEMA_VERSION
        assert con.execute("SELECT id FROM jobs").fetchone()[0] == job
    backups = list((project.root / "backups").glob("*.sqlite3"))
    assert len(backups) == 1
    with database.connect(backups[0], readonly=True) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 3


def test_evaluation_rejects_cross_split_leakage(tmp_path):
    root = synthetic(tmp_path / "data", 6)
    test = next((root / "errors/test").rglob("*.jpg"))
    train = next((root / "errors/train").rglob("*.jpg"))
    train.write_bytes(test.read_bytes())
    project = create_project(tmp_path / "project", "leak")
    import_dataset(project, root)
    job = create_job(project, create_plan(project), RunConfig())
    run = run_job(project, job)["run_id"]
    compare_run(project, run)
    approve(project, run)
    with pytest.raises(ValueError, match="leakage"):
        create_golden(project, run, "test", purpose="evaluation", split="test")
