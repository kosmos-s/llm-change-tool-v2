import csv
import json
import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication
from test_reviews import prepared

from llm_change_tool.core.evaluation import (
    compare_model_evaluations,
    export_comparison_report,
    verify_manual_counts,
)
from llm_change_tool.core.labels import KEYS, canonical
from llm_change_tool.core.metrics import (
    create_golden,
    export_golden_template,
    import_model_predictions,
    label_metrics,
    model_comparison,
    model_evaluation,
)
from llm_change_tool.core.reviews import compare_run, review_queue, save_review
from llm_change_tool.storage.store import execute, transaction
from llm_change_tool.ui.components import DashboardPanel


def labels(**positive):
    return dict(dict.fromkeys(KEYS, 0), **positive)


def reference(project, *, split="test"):
    run = prepared(project)
    compare_run(project, run)
    truth = {}
    chosen = [s for s in review_queue(project, run) if s["split"] == split]
    for index, sample in enumerate(chosen):
        values = labels(tree=1) if index == 0 else labels()
        save_review(project, run, sample["id"], values, "Synthetic known truth", "synthetic tester")
        truth[sample["id"]] = values
    golden = create_golden(
        project, run, "Synthetic fixed reference", purpose="evaluation", split=split
    )
    return golden, truth


def pair(project, split="test"):
    golden, truth = reference(project, split=split)
    baseline = model_evaluation(project, golden["id"], "baseline", {sid: labels() for sid in truth})
    retrained = model_evaluation(project, golden["id"], "retrained", truth)
    return golden, truth, baseline, retrained


def test_scene_primary_differs_from_label_micro_and_ignores_children():
    report = label_metrics({"a": labels(arti=1, arti_bu=1, tree=1)}, {"a": labels(water=1)})
    assert report["primary_metric"] == "scene.f1"
    assert report["scene"]["f1"] == 1 and report["overall"]["f1"] == 0
    assert report["scene"]["tp"] == 1 and report["overall"]["fn"] == 2
    assert report["scene"]["labels"] == ["arti", "tree", "fore", "farm", "water"]
    # Inactive/legacy children and excluded road marks alone do not define scene change.
    child = next(k for k in KEYS if k not in report["scene"]["labels"])
    assert not label_metrics({"a": labels(**{child: 1})}, {"a": labels()})["scene"]["defined"]


def test_scene_known_counts_partial_coverage_and_undefined():
    truth = {str(i): labels(tree=int(i < 2)) for i in range(4)}
    predictions = {str(i): labels(water=int(i in (0, 2))) for i in range(4)}
    scene = label_metrics(truth, predictions)["scene"]
    assert [scene[k] for k in ("tp", "fp", "fn", "tn")] == [1, 1, 1, 1]
    assert scene["f1"] == 0.5
    del predictions["3"]
    report = label_metrics(truth, predictions)
    assert report["coverage"] == 0.75 and report["scene"]["tn"] == 0
    assert label_metrics({}, {})["scene"] is None
    assert not label_metrics({"a": labels()}, {"a": labels()})["scene"]["defined"]
    with pytest.raises(ValueError):
        label_metrics({"a": labels(tree=None)}, {"a": labels()})


def test_paired_delta_and_manual_audit_export(imported):
    project, _ = imported
    golden, truth, baseline, retrained = pair(project)
    report = compare_model_evaluations(
        project, baseline["evaluation_id"], retrained["evaluation_id"]
    )
    assert report["final_test_eligible"] and report["delta_f1"] == 1
    assert report["delta_percentage_points"] == 100 and report["delta_counts"]["fn"] == -1
    assert report["manual_review_status"] == "pending"
    exported = export_comparison_report(
        project, baseline["evaluation_id"], retrained["evaluation_id"]
    )
    audit = list(
        csv.DictReader(Path(exported["manual_audit_path"]).open(encoding="utf-8-sig", newline=""))
    )
    assert len(audit) == len(truth)
    assert {r["case_change"] for r in audit} == {"corrected", "both_correct"}
    assert all(not r["manual_checked"] and not r["manual_notes"] for r in audit)
    saved = json.loads(Path(exported["path"]).read_text(encoding="utf-8"))
    assert saved["golden_fingerprint"] == golden["fingerprint"]
    assert verify_manual_counts(retrained, dict(tp=1, fp=0, fn=0, tn=1))["matches"]
    assert not verify_manual_counts(retrained, dict(tp=0, fp=0, fn=1, tn=1))["matches"]
    with pytest.raises(ValueError):
        verify_manual_counts(retrained, dict(tp=-1, fp=0, fn=0, tn=3))


def test_comparison_rejects_different_or_changed_truth_and_legacy(imported):
    project, _ = imported
    golden, _, baseline, retrained = pair(project)
    with pytest.raises(ValueError, match="different"):
        compare_model_evaluations(project, baseline["evaluation_id"], baseline["evaluation_id"])
    _, _, other, _ = pair(project, split="val")
    with pytest.raises(ValueError, match="same fixed"):
        compare_model_evaluations(project, baseline["evaluation_id"], other["evaluation_id"])
    with transaction(project) as con:
        execute(
            con,
            "UPDATE golden_items SET labels=:labels WHERE set_id=:id",
            labels=canonical(labels(water=1)),
            id=golden["id"],
        )
    with pytest.raises(ValueError, match="reference changed"):
        compare_model_evaluations(project, baseline["evaluation_id"], retrained["evaluation_id"])
    with transaction(project) as con:
        old = dict(other)
        for key in ("scene", "scene_cases", "evaluation_policy"):
            del old[key]
        execute(
            con,
            "UPDATE model_evaluations SET payload=:payload WHERE id=:id",
            payload=canonical(old),
            id=other["evaluation_id"],
        )
    assert any("scene" not in r for r in model_comparison(project))
    with pytest.raises(ValueError, match="Legacy"):
        compare_model_evaluations(project, other["evaluation_id"], retrained["evaluation_id"])


def test_val_is_reference_only_and_templates_require_actual_predictions(imported):
    project, _ = imported
    golden, truth, baseline, retrained = pair(project, split="val")
    assert not compare_model_evaluations(
        project, baseline["evaluation_id"], retrained["evaluation_id"]
    )["final_test_eligible"]
    path = Path(export_golden_template(project, golden["id"])["path"])
    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data["inputs"]) == set(truth)
    assert all("json" not in row["images"] for row in data["inputs"].values())
    assert all(row["split"] == "val" for row in data["inputs"].values())
    assert all(v is None for item in data["predictions"].values() for v in item.values())
    with pytest.raises(ValueError, match="template"):
        import_model_predictions(project, path, "not actual")
    data["prediction_status"] = "complete"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        import_model_predictions(project, path, "unfilled")
    data["predictions"] = truth
    data["golden_fingerprint"] = "wrong"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="fingerprint"):
        import_model_predictions(project, path, "wrong reference")
    data["golden_fingerprint"] = golden["fingerprint"]
    path.write_text(json.dumps(data), encoding="utf-8")
    assert import_model_predictions(project, path, "actual fixture")["scene"]["f1"] == 1
    # Existing v1 prediction files remain importable.
    path.write_text(json.dumps(dict(golden_id=golden["id"], predictions=truth)), encoding="utf-8")
    assert import_model_predictions(project, path, "legacy format")["matched"] == len(truth)


def test_ui_separates_primary_secondary_and_legacy():
    app = QApplication.instance() or QApplication([])
    panel = DashboardPanel()
    report = dict(name="Synthetic", **label_metrics({"a": labels(tree=1)}, {"a": labels(water=1)}))
    panel.set_result([report])
    assert "변화 유무 F1 100.0%" in panel.overall.text()
    assert "보조 micro F1 0.0%" in panel.overall.text()
    assert "대표" in panel.metric_table.item(0, 0).text()
    assert "micro" in panel.metric_table.item(1, 0).text()
    assert panel.metric_table.item(0, 5).text() == "1"
    del report["scene"]
    panel.set_result([report])
    assert "이전 기록" in panel.overall.text()
    panel.close()
    app.processEvents()


def test_offline_cli_reopen_backup_and_export(imported, tmp_path):
    from llm_change_tool.core.exporting import export_run, final_gate
    from llm_change_tool.core.projects import backup_project, open_project, restore_project

    project, source = imported
    before = {p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()}
    golden, truth = reference(project)
    with transaction(project, readonly=True) as con:
        run = con.exec_driver_sql("SELECT run_id FROM jobs").scalar()
    for sample in review_queue(project, run):
        if sample["review_state"] != "DONE":
            save_review(project, run, sample["id"], labels(), "Synthetic only", "synthetic tester")
    project = open_project(project.root)
    assert final_gate(project, run)["all_human_reviewed"]
    output = export_run(project, run)
    assert len(list(Path(output["path"]).rglob("*_combined.json"))) == 6
    files = []
    for name, predictions in (("before", {sid: labels() for sid in truth}), ("after", truth)):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(dict(golden_id=golden["id"], predictions=predictions)))
        files.append(path)
    process = subprocess.run(
        [
            sys.executable,
            "scripts/evaluate_models.py",
            str(project.root),
            "--baseline",
            str(files[0]),
            "--retrained",
            str(files[1]),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert process.returncode == 0, process.stderr
    report = json.loads(process.stdout)
    assert report["delta_percentage_points"] == 100
    assert report["manual_review_status"] == "pending"
    restored = restore_project(backup_project(project), tmp_path / "restored")
    evaluations = model_comparison(restored)
    paired = compare_model_evaluations(
        restored, evaluations[0]["evaluation_id"], evaluations[1]["evaluation_id"]
    )
    assert paired["delta_f1"] == 1
    assert final_gate(restored, run)["all_human_reviewed"]
    assert before == {
        p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()
    }
