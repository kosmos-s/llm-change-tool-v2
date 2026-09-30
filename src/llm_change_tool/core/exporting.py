"""Final Gate and atomic, provenance-bound exports of original-compatible JSON."""

import json
import shutil
from pathlib import Path
from uuid import uuid4

from llm_change_tool.core.datasets import quality_issues, safe_path, sha, verify_sources
from llm_change_tool.core.jobs import validate_run
from llm_change_tool.core.labels import (
    Prediction,
    canonical,
    effective_doc,
    import_labels,
    strict_json,
    validate_labels,
)
from llm_change_tool.core.locking import worker_lock
from llm_change_tool.core.plans import validate_plan
from llm_change_tool.core.projects import now
from llm_change_tool.core.reviews import latest_review, result_binding
from llm_change_tool.storage.store import execute, one, rows, transaction


def gate_in_transaction(con, run_id):
    problems = []
    effective = []
    run = one(con, "SELECT * FROM llm_runs WHERE id=:id", id=run_id)
    config = validate_run(con, run)
    plan, samples = validate_plan(con, run["plan_id"])
    job = one(con, "SELECT * FROM jobs WHERE run_id=:run", run=run_id)
    if job["state"] != "COMPLETED":
        problems.append("AI job is not COMPLETED")
    if plan["mode"] == "production" and config.provider != "openai":
        problems.append("OpenAI production coverage missing")
    counts = {
        "total": len(samples),
        "ai_success": 0,
        "compare_complete": 0,
        "review_decisions": 0,
        "deferred": 0,
        "review_required": 0,
        "human_complete": 0,
        "english_reason_missing": 0,
    }
    for sample in samples:
        sid = sample["id"]
        prefix = sample["logical_key"]
        items = rows(
            con,
            "SELECT * FROM job_items WHERE job_id=:job AND sample_id=:sid",
            job=job["id"],
            sid=sid,
        )
        results = rows(
            con,
            "SELECT * FROM llm_results WHERE run_id=:run AND sample_id=:sid",
            run=run_id,
            sid=sid,
        )
        comparisons = rows(
            con,
            "SELECT * FROM comparisons WHERE run_id=:run AND sample_id=:sid",
            run=run_id,
            sid=sid,
        )
        if not items or items[0]["state"] != "COMPLETED" or items[0]["error"] or not results:
            problems.append(prefix + ": unresolved API error or missing success")
            continue
        try:
            Prediction.model_validate_json(results[0]["prediction"])
        except ValueError:
            problems.append(prefix + ": malformed output")
            continue
        counts["ai_success"] += 1
        if not comparisons:
            problems.append(prefix + ": missing comparison/review-list entry")
            continue
        comp = comparisons[0]
        counts["compare_complete"] += 1
        binding = result_binding(sample, results[0]["prediction"], items[0]["error"])
        if binding != comp["result_hash"]:
            problems.append(prefix + ": stale comparison")
            continue
        review = latest_review(con, run_id, sid)
        if comp["required"]:
            counts["review_required"] += 1
        if review:
            if review["state"] == "DEFERRED":
                counts["deferred"] += 1
            if review["state"] != "DONE" or review["result_hash"] != binding:
                problems.append(prefix + ": deferred/draft/stale human review")
                continue
            labels = json.loads(review["labels"])
            reason = review["reason"]
            counts["human_complete"] += 1
        elif (
            comp["required"]
            or comp["decision"] != "AUTO_KEEP"
            or import_labels(strict_json(sample["original_raw"])[0])[1]
        ):
            problems.append(prefix + ": required human review unresolved")
            continue
        else:
            labels = json.loads(sample["original_labels"])
            reason = ""
        try:
            validate_labels(labels)
            doc = (
                effective_doc(sample["original_raw"], labels, reason, review["reason_en"])
                if review
                else effective_doc(sample["original_raw"], labels, "")
            )
            if not review and doc == strict_json(sample["original_raw"])[0]:
                doc = None
        except ValueError as exc:
            problems.append(prefix + ": effective JSON error: " + str(exc))
            continue
        counts["review_decisions"] += 1
        if doc and doc.get("reason_ko") and not doc.get("reason"):
            counts["english_reason_missing"] += 1
        effective.append((sample, review, doc))
    conflicts = execute(
        con, "SELECT count(*) FROM merge_conflicts WHERE run_id=:run AND state='OPEN'", run=run_id
    ).scalar()
    if conflicts:
        problems.append(f"Unresolved team conflicts: {conflicts}")
    return (
        {"passed": not problems, "mode": plan["mode"], "problems": problems, "counts": counts},
        effective,
        run,
        plan,
    )


def run_mode(project, run_id):
    with transaction(project) as con:
        return one(
            con,
            """SELECT p.mode FROM work_plans p JOIN llm_runs r
                   ON r.plan_id=p.id WHERE r.id=:id""",
            id=run_id,
        )["mode"]


def final_gate(project, run_id):
    errors = verify_sources(project, run_mode(project, run_id))
    try:
        with transaction(project) as con:
            report, _, _, _ = gate_in_transaction(con, run_id)
    except ValueError as exc:
        report = {"passed": False, "problems": [str(exc)], "counts": {}}
    report["problems"].extend("Dataset quality/integrity: " + str(error) for error in errors)
    report["passed"] = not report["problems"]
    return report


def export_run(project, run_id, destination: Path | None = None):
    with worker_lock(project):
        errors = verify_sources(project, run_mode(project, run_id))
        if errors:
            raise ValueError(f"Dataset quality/integrity errors: {len(errors)}")
        with transaction(project) as con:
            gate, effective, run, plan = gate_in_transaction(con, run_id)
            if not gate["passed"]:
                raise ValueError("Final Gate blocked: " + "; ".join(gate["problems"][:8]))
            dataset = one(con, "SELECT * FROM datasets")
            source = Path(dataset["root"]).resolve()
            sid = str(uuid4())
            destination = (
                destination or project.root / "exports" / f"{plan['mode']}-{sid}"
            ).resolve()
            if destination.is_relative_to(source) or source.is_relative_to(destination):
                raise ValueError("Export destination overlaps original dataset")
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                raise FileExistsError(destination)
            staging = destination.parent / f".incomplete-{sid}"
            staging.mkdir(exist_ok=False)
            try:
                entries = []
                for sample, review, doc in effective:
                    paths = json.loads(sample["paths"])
                    hashes = json.loads(sample["hashes"])
                    file_hashes = {}
                    for role, relative in paths.items():
                        output = safe_path(staging, relative)
                        output.parent.mkdir(parents=True, exist_ok=True)
                        if role == "json":
                            raw = (
                                (json.dumps(doc, ensure_ascii=False, indent=2) + "\n").encode(
                                    "utf-8"
                                )
                                if doc
                                else sample["original_raw"]
                            )
                            output.write_bytes(raw)
                        else:
                            shutil.copyfile(safe_path(source, relative), output)
                            if sha(output) != hashes[role]:
                                raise ValueError("Source image changed during export")
                        file_hashes[relative] = sha(output)
                    entries.append(
                        {
                            "sample_id": sample["id"],
                            "logical_key": sample["logical_key"],
                            "review_revision": review["revision"] if review else None,
                            "english_reason_missing": bool(
                                doc and doc.get("reason_ko") and not doc.get("reason")
                            ),
                            "files": file_hashes,
                            "source_hashes": hashes,
                        }
                    )
                manifest = {
                    "format": "llm-change-export-v1",
                    "id": sid,
                    "mode": plan["mode"],
                    "production": plan["mode"] == "production",
                    "quality_issues": quality_issues(json.loads(dataset["quality"]), plan["mode"]),
                    "dataset_fingerprint": dataset["fingerprint"],
                    "plan_fingerprint": plan["fingerprint"],
                    "run_config_hash": run["config_hash"],
                    "prompt_sha256": run["prompt_hash"],
                    "schema_sha256": run["schema_hash"],
                    "timestamp": now(),
                    "gate": gate,
                    "samples": entries,
                }
                (staging / "manifest.json").write_text(canonical(manifest), encoding="utf-8")
                if destination.exists():
                    raise FileExistsError(destination)
                staging.rename(destination)
                execute(
                    con,
                    "INSERT INTO snapshots VALUES (:id,:run,:manifest,:time)",
                    id=sid,
                    run=run_id,
                    manifest=canonical(manifest),
                    time=now(),
                )
            except Exception:
                shutil.rmtree(staging, ignore_errors=True)
                raise
        return {"path": str(destination), "samples": len(effective), "mode": plan["mode"]}
