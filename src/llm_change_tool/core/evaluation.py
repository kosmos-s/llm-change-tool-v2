"""Paired, fixed-reference model comparison and local manual-audit exports."""

import csv
import io
import json
from pathlib import Path
from uuid import uuid4

from llm_change_tool.core.labels import SCHEMA_HASH, canonical, digest
from llm_change_tool.core.metrics import EVALUATION_POLICY, binary_metrics, scene_change
from llm_change_tool.storage.store import one, rows, transaction


def _evaluation(con, evaluation_id):
    row = one(con, "SELECT * FROM model_evaluations WHERE id=:id", id=evaluation_id)
    report = json.loads(row["payload"])
    if report.get("evaluation_policy") != EVALUATION_POLICY or not report.get("scene_cases"):
        raise ValueError(
            "Legacy evaluation has no scene predictions; import actual predictions again"
        )
    golden = one(con, "SELECT * FROM golden_sets WHERE id=:id", id=row["golden_id"])
    truth = {
        r["sample_id"]: json.loads(r["labels"])
        for r in rows(con, "SELECT * FROM golden_items WHERE set_id=:id", id=row["golden_id"])
    }
    if (
        report.get("golden_fingerprint") != golden["fingerprint"]
        or report.get("truth_hash") != digest(truth)
        or report.get("schema_hash") != SCHEMA_HASH
    ):
        raise ValueError("Evaluation reference changed; use the original fixed golden set")
    cases = report["scene_cases"]
    by_id = {case["sample_id"]: case for case in cases}
    if len(by_id) != len(cases) or set(by_id) != set(truth) or report.get("coverage") != 1:
        raise ValueError("Paired comparison requires complete predictions")
    for sid, labels in truth.items():
        if by_id[sid]["truth"] != scene_change(labels):
            raise ValueError("Evaluation reference changed")
    counts = binary_metrics(
        [by_id[sid]["truth"] for sid in sorted(truth)],
        [by_id[sid]["prediction"] for sid in sorted(truth)],
    )
    if any(counts[key] != report["scene"][key] for key in counts):
        raise ValueError("Evaluation scene counts are inconsistent")
    report["evaluation_id"] = evaluation_id
    return report


def compare_model_evaluations(project, baseline_id, candidate_id):
    if baseline_id == candidate_id:
        raise ValueError("Choose different baseline and retrained evaluations")
    with transaction(project, readonly=True) as con:
        baseline, candidate = _evaluation(con, baseline_id), _evaluation(con, candidate_id)
        if (
            baseline["golden_id"] != candidate["golden_id"]
            or baseline["truth_hash"] != candidate["truth_hash"]
        ):
            raise ValueError("Baseline and retrained models must use the same fixed golden set")
    defined = baseline["scene"]["defined"] and candidate["scene"]["defined"]
    delta = candidate["scene"]["f1"] - baseline["scene"]["f1"] if defined else None
    return {
        "kind": "paired_model_comparison",
        "evaluation_policy": EVALUATION_POLICY,
        "primary_metric": "scene.f1",
        "golden_id": baseline["golden_id"],
        "golden_fingerprint": baseline["golden_fingerprint"],
        "purpose": baseline["purpose"],
        "split": baseline["split"],
        "final_test_eligible": baseline["purpose"] == "evaluation" and baseline["split"] == "test",
        "baseline": baseline,
        "candidate": candidate,
        "delta_f1": delta,
        "delta_percentage_points": 100 * delta if delta is not None else None,
        "delta_counts": {
            k: candidate["scene"][k] - baseline["scene"][k] for k in ("tp", "fp", "fn", "tn")
        },
        "manual_review_status": "pending",
        "note": "Internal scene-level comparison. Manual audit is pending; this does not establish a company target or statistical significance.",
    }


def load_model_evaluation(project, evaluation_id):
    with transaction(project, readonly=True) as con:
        return _evaluation(con, evaluation_id)


def verify_manual_counts(report, counts):
    """Cross-check independently tallied TP/FP/FN/TN without changing truth."""
    if set(counts) != {"tp", "fp", "fn", "tn"} or any(
        type(v) is not int or v < 0 for v in counts.values()
    ):
        raise ValueError("Enter non-negative integer TP/FP/FN/TN counts")
    expected = report.get("scene")
    if not expected:
        raise ValueError("Scene evaluation is unavailable")
    denom = 2 * counts["tp"] + counts["fp"] + counts["fn"]
    return {
        "matches": all(counts[k] == expected[k] for k in counts),
        "total": sum(counts.values()),
        "f1": 2 * counts["tp"] / denom if denom else None,
        "note": "Counts check only; image interpretation still requires a human.",
    }


def _csv_cell(value):
    text = str(value)
    return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text


def export_comparison_report(project, baseline_id, candidate_id):
    report = compare_model_evaluations(project, baseline_id, candidate_id)
    baseline = {case["sample_id"]: case for case in report["baseline"]["scene_cases"]}
    candidate = {case["sample_id"]: case for case in report["candidate"]["scene_cases"]}
    with transaction(project, readonly=True) as con:
        source = Path(one(con, "SELECT root FROM datasets")["root"]).resolve()
        samples = {r["id"]: r for r in rows(con, "SELECT id,logical_key,split FROM samples")}
    folder = (project.root / "exports").resolve()
    if folder.is_relative_to(source) or source.is_relative_to(folder):
        raise ValueError("Evaluation export overlaps original dataset")
    folder.mkdir(parents=True, exist_ok=True)
    bundle_id = uuid4().hex
    report_path = folder / f"evaluation-{bundle_id}.json"
    audit_path = folder / f"evaluation-{bundle_id}-manual.csv"
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "sample_id",
            "logical_key",
            "split",
            "truth_change",
            "baseline_change",
            "retrained_change",
            "baseline_outcome",
            "retrained_outcome",
            "case_change",
            "manual_checked",
            "manual_notes",
        ]
    )
    for sid in sorted(baseline):
        old, new = baseline[sid], candidate[sid]
        old_ok, new_ok = old["truth"] == old["prediction"], new["truth"] == new["prediction"]
        change = (
            "both_correct"
            if old_ok and new_ok
            else "corrected"
            if new_ok
            else "regressed"
            if old_ok
            else "both_wrong"
        )
        writer.writerow(
            [
                _csv_cell(v)
                for v in (
                    sid,
                    samples[sid]["logical_key"],
                    samples[sid]["split"],
                    old["truth"],
                    old["prediction"],
                    new["prediction"],
                    old["outcome"],
                    new["outcome"],
                    change,
                    "",
                    "",
                )
            ]
        )
    with audit_path.open("x", encoding="utf-8-sig", newline="") as stream:
        stream.write(buffer.getvalue())
    report["manual_audit_file"] = audit_path.name
    with report_path.open("x", encoding="utf-8") as stream:
        stream.write(canonical(report))
    return {"path": str(report_path), "manual_audit_path": str(audit_path), **report}
