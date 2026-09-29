import json

import pytest
from conftest import synthetic

from llm_change_tool.core.datasets import import_dataset, scan_dataset, verify_sources
from llm_change_tool.core.exporting import export_run, final_gate
from llm_change_tool.core.jobs import RunConfig, create_job, job_info, run_job
from llm_change_tool.core.labels import effective_doc, import_labels, original_labels
from llm_change_tool.core.plans import create_plan
from llm_change_tool.core.projects import create_project
from llm_change_tool.core.reviews import compare_run, save_review
from llm_change_tool.storage.store import rows, transaction


def alter(root, change):
    path = sorted(root.rglob("*.json"))[0]
    doc = json.loads(path.read_text(encoding="utf-8"))
    change(doc)
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


@pytest.mark.parametrize("issue", ["leakage", "duplicate", "missing_active", "contradiction"])
def test_pilot_flow_and_production_block(tmp_path, issue):
    root = synthetic(tmp_path / "dataset_sample", 4)
    if issue in ("leakage", "duplicate"):
        images = sorted(root.rglob("*.jpg"))
        if issue == "duplicate":
            images = list((root / "errors/train").rglob("*.jpg"))
        images[1].write_bytes(images[0].read_bytes())
    elif issue == "missing_active":
        alter(root, lambda d: (d.update(Artifact="o"), d["artifact_detail"].pop("arti_bu")))
    else:
        alter(root, lambda d: d["artifact_detail"].update(arti_bu="o"))
    project = create_project(tmp_path / "project", "pilot")
    report = import_dataset(project, root)
    assert report["samples"] == 4
    assert not any(e["error"] == "orphan_image" for e in report["errors"])
    assert verify_sources(project, "pilot") == []
    with pytest.raises(ValueError, match="quality"):
        create_plan(project, "production")
    job = create_job(project, create_plan(project, "pilot"), RunConfig())
    run_job(project, job)
    assert job_info(project, job)["state"] == "COMPLETED"
    run_job(project, job)  # same validation on resume
    run = job_info(project, job)["run_id"]
    compare_run(project, run)
    assert not final_gate(project, run)["passed"]
    with transaction(project) as con:
        samples = rows(
            con, "SELECT s.*,r.prediction FROM samples s JOIN llm_results r ON r.sample_id=s.id"
        )
        comparisons = rows(con, "SELECT * FROM comparisons")
    if issue in ("missing_active", "contradiction"):
        assert any(
            "source_labels" in json.loads(c["signals"]) and c["required"] for c in comparisons
        )
    for sample in samples:
        save_review(
            project,
            run,
            sample["id"],
            json.loads(sample["prediction"])["labels"],
            "이미지 확인 후 수정",
            "tester",
            "DONE",
            None,
        )
    assert final_gate(project, run)["passed"]
    result = export_run(project, run)
    from pathlib import Path

    manifest = json.loads((Path(result["path"]) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["production"] is False
    assert all(e["severity"] == "WARNING" for e in manifest["quality_issues"])


def test_inactive_missing_detail_normalizes_without_source_edit(tmp_path):
    root = synthetic(tmp_path / "data", 1)
    path = alter(root, lambda d: d.pop("artifact_detail"))
    raw = path.read_bytes()
    samples, errors, _ = scan_dataset(root)
    assert not errors
    labels = json.loads(samples[0]["original_labels"])
    assert labels["arti_bu"] == 0
    assert original_labels(effective_doc(raw, labels, "")) == labels
    assert path.read_bytes() == raw


@pytest.mark.parametrize("damage", ["json", "missing", "corrupt"])
@pytest.mark.parametrize("mode", ["pilot", "production"])
def test_fatal_in_both_modes(tmp_path, damage, mode):
    root = synthetic(tmp_path / "data", 3)
    path = sorted(root.rglob("*.json"))[0]
    image = path.with_suffix(".jpg")
    if damage == "json":
        path.write_text("{")
    elif damage == "missing":
        image.unlink()
    else:
        image.write_bytes(b"broken image")
    project = create_project(tmp_path / "project", "fatal")
    report = import_dataset(project, root)
    assert not any(e["error"] == "orphan_image" for e in report["errors"])
    with pytest.raises(ValueError, match="quality"):
        create_plan(project, mode)


def test_active_missing_is_unknown(tmp_path):
    root = synthetic(tmp_path / "data", 1)
    path = alter(root, lambda d: (d.update(Artifact="o"), d["artifact_detail"].pop("arti_bu")))
    labels, issues = import_labels(json.loads(path.read_text(encoding="utf-8")))
    assert labels["arti_bu"] is None and issues
