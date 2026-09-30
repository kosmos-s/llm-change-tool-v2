"""Separate VLM-vs-human evaluation from baseline/retrained model evaluation."""

import json
from pathlib import Path
from uuid import uuid4

from llm_change_tool.core.labels import KEYS, canonical, digest, validate_labels
from llm_change_tool.core.projects import now
from llm_change_tool.storage.store import execute, one, rows, transaction


def binary_metrics(truth, prediction):
    if len(truth) != len(prediction) or not truth:
        raise ValueError("Non-empty equal-size arrays required")
    if any(type(x) is not int or x not in (0, 1) for x in [*truth, *prediction]):
        raise ValueError("Binary integer values required")
    tp = sum(t == 1 and p == 1 for t, p in zip(truth, prediction, strict=True))
    fp = sum(t == 0 and p == 1 for t, p in zip(truth, prediction, strict=True))
    fn = sum(t == 1 and p == 0 for t, p in zip(truth, prediction, strict=True))
    tn = sum(t == 0 and p == 0 for t, p in zip(truth, prediction, strict=True))
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": tp / (tp + fp) if tp + fp else 0,
        "recall": tp / (tp + fn) if tp + fn else 0,
        "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0,
        "f2": 5 * tp / (5 * tp + fp + 4 * fn) if 5 * tp + fp + 4 * fn else 0,
    }


def label_metrics(truth, predictions):
    ids = sorted(set(truth) & set(predictions))
    return {
        "coverage": len(ids) / len(truth) if truth else 0,
        "matched": len(ids),
        "reference": len(truth),
        "metrics": {
            key: binary_metrics([truth[s][key] for s in ids], [predictions[s][key] for s in ids])
            for key in KEYS
        }
        if ids
        else {},
    }


def dashboard(project, run_id=None):
    with transaction(project) as con:
        result = {"sample_total": execute(con, "SELECT count(*) FROM samples").scalar()}
        if not run_id:
            return result
        job = one(con, "SELECT * FROM jobs WHERE run_id=:run", run=run_id)
        counts = {
            r["state"]: r["n"]
            for r in rows(
                con,
                "SELECT state,count(*) n FROM job_items WHERE job_id=:job GROUP BY state",
                job=job["id"],
            )
        }
        result.update(
            job_state=job["state"],
            AI_success=counts.get("COMPLETED", 0),
            AI_failed=counts.get("FAILED", 0),
            pending=counts.get("PENDING", 0),
            running=counts.get("RUNNING", 0),
        )
        result.update(
            one(
                con,
                """SELECT coalesce(sum(input_tokens),0) input_tokens,
            coalesce(sum(output_tokens),0) output_tokens,coalesce(sum(charged_cost),0) estimated_cost,
            coalesce(sum(CASE WHEN state IN ('RUNNING','UNKNOWN') THEN reserved_cost ELSE 0 END),0) unresolved_reserve
            FROM attempts WHERE job_id=:job""",
                job=job["id"],
            )
        )
        comps = rows(con, "SELECT * FROM comparisons WHERE run_id=:run", run=run_id)
        result.update(
            compare_complete=len(comps), review_required=sum(c["required"] for c in comps)
        )
        values = rows(
            con,
            """SELECT s.id,s.original_labels,r.prediction,v.labels,v.state,v.result_hash review_hash,c.result_hash comparison_hash FROM samples s
            JOIN job_items i ON i.sample_id=s.id AND i.job_id=:job
            LEFT JOIN llm_results r ON r.sample_id=s.id AND r.run_id=:run
            LEFT JOIN comparisons c ON c.sample_id=s.id AND c.run_id=:run
            LEFT JOIN reviews v ON v.revision=(SELECT max(revision) FROM reviews WHERE run_id=:run AND sample_id=s.id)""",
            job=job["id"],
            run=run_id,
        )
        done = [
            v for v in values if v["state"] == "DONE" and v["review_hash"] == v["comparison_hash"]
        ]
        result["review_completed"] = len(done)
        result["deferred"] = sum(v["state"] == "DEFERRED" for v in values)
        result["drafts"] = sum(v["state"] == "DRAFT" for v in values)
        result["modified"] = sum(
            json.loads(v["labels"]) != json.loads(v["original_labels"]) for v in done
        )
        auto = {c["sample_id"] for c in comps if c["decision"] == "AUTO_KEEP"}
        result["original_kept"] = (
            len(done) - result["modified"] + sum(v["id"] in auto and not v["state"] for v in values)
        )
        paired = [v for v in done if v["prediction"]]
        result["GPT_human_agreement"] = (
            sum(json.loads(v["labels"]) == json.loads(v["prediction"])["labels"] for v in paired)
            / len(paired)
            if paired
            else None
        )
        truth = {v["id"]: json.loads(v["labels"]) for v in done}
        predictions = {v["id"]: json.loads(v["prediction"])["labels"] for v in paired}
        result["VLM_vs_human"] = label_metrics(truth, predictions)
        return result


def create_golden(project, run_id, name, sample_ids=None, *, purpose="exploration", split=None):
    if not name.strip():
        raise ValueError("Golden set name required")
    if purpose not in ("exploration", "training", "evaluation") or split not in (
        None,
        "train",
        "val",
        "test",
    ):
        raise ValueError("Invalid golden purpose/split")
    if purpose == "evaluation" and split not in ("val", "test"):
        raise ValueError("평가용은 val 또는 test 하나를 선택하세요.")
    if purpose == "training" and split != "train":
        raise ValueError("학습용은 train을 선택하세요.")
    from llm_change_tool.core.datasets import verify_sources

    if verify_sources(project, "pilot"):
        raise ValueError("Source integrity errors")
    with transaction(project) as con:
        dataset = one(con, "SELECT * FROM datasets")
        values = rows(
            con,
            """SELECT v.* FROM reviews v JOIN comparisons c ON c.run_id=v.run_id AND c.sample_id=v.sample_id
            WHERE v.run_id=:run AND v.state='DONE' AND v.result_hash=c.result_hash AND v.revision=(SELECT max(revision) FROM reviews
            WHERE sample_id=v.sample_id AND run_id=:run) ORDER BY v.sample_id""",
            run=run_id,
        )
        from llm_change_tool.core.quality import image_identity

        samples = rows(con, "SELECT * FROM samples")
        by_id = {s["id"]: s for s in samples}
        if split:
            values = [v for v in values if by_id[v["sample_id"]]["split"] == split]
        if sample_ids is not None:
            values = [v for v in values if v["sample_id"] in sample_ids]
        if not values:
            raise ValueError("Human-confirmed reviews required")
        if purpose == "evaluation":
            selected_hashes = [image_identity(by_id[v["sample_id"]]) for v in values]
            other_hashes = {image_identity(s) for s in samples if s["split"] != split}
            if (
                len(set(selected_hashes)) != len(selected_hashes)
                or set(selected_hashes) & other_hashes
            ):
                raise ValueError("평가용 데이터에 중복 또는 split leakage가 있습니다.")
        fp = digest(
            {
                "purpose": purpose,
                "split": split,
                "dataset": dataset["fingerprint"],
                "items": [(v["sample_id"], v["labels"], v["revision"]) for v in values],
            }
        )
        gid = str(uuid4())
        execute(
            con,
            "INSERT INTO golden_sets VALUES (:id,:name,:fp,:time)",
            id=gid,
            name=name.strip(),
            fp=fp,
            time=now(),
        )
        execute(
            con,
            "INSERT INTO golden_metadata VALUES (:id,:purpose,:split,:run,:payload)",
            id=gid,
            purpose=purpose,
            split=split or "mixed",
            run=run_id,
            payload=canonical(
                {
                    "dataset_fingerprint": dataset["fingerprint"],
                    "duplicate_check": purpose == "evaluation",
                }
            ),
        )
        for v in values:
            execute(
                con,
                "INSERT INTO golden_items VALUES (:gid,:sid,:labels,:revision)",
                gid=gid,
                sid=v["sample_id"],
                labels=v["labels"],
                revision=v["revision"],
            )
        return {
            "id": gid,
            "name": name,
            "samples": len(values),
            "fingerprint": fp,
            "purpose": purpose,
            "split": split,
        }


def evaluate_golden(project, golden_id):
    with transaction(project) as con:
        gold = one(con, "SELECT * FROM golden_sets WHERE id=:id", id=golden_id)
        truth = {
            r["sample_id"]: json.loads(r["labels"])
            for r in rows(con, "SELECT * FROM golden_items WHERE set_id=:id", id=golden_id)
        }
        result = []
        for run in rows(con, "SELECT * FROM llm_runs ORDER BY created_at"):
            predictions = {
                r["sample_id"]: json.loads(r["prediction"])["labels"]
                for r in rows(con, "SELECT * FROM llm_results WHERE run_id=:id", id=run["id"])
            }
            result.append(
                {
                    "run_id": run["id"],
                    "model": json.loads(run["config"])["model"],
                    "provider": json.loads(run["config"])["provider"],
                    "prompt_hash": run["prompt_hash"],
                    **label_metrics(truth, predictions),
                }
            )
        metadata = rows(con, "SELECT * FROM golden_metadata WHERE set_id=:id", id=golden_id)
        return {
            "golden": gold,
            "purpose": metadata[0] if metadata else {"purpose": "legacy-unspecified"},
            "runs": result,
        }


def model_evaluation(project, golden_id, name, predictions):
    if not name.strip():
        raise ValueError("Model name required")
    with transaction(project) as con:
        one(con, "SELECT * FROM golden_sets WHERE id=:id", id=golden_id)
        truth = {
            r["sample_id"]: json.loads(r["labels"])
            for r in rows(con, "SELECT * FROM golden_items WHERE set_id=:id", id=golden_id)
        }
        if set(predictions) != set(truth):
            raise ValueError("Model predictions must cover exactly the golden sample IDs")
        for labels in predictions.values():
            validate_labels(labels)
        metadata = rows(
            con, "SELECT purpose,split FROM golden_metadata WHERE set_id=:id", id=golden_id
        )
        report = {
            "purpose": metadata[0]["purpose"] if metadata else "legacy-unspecified",
            "split": metadata[0]["split"] if metadata else "unspecified",
            "name": name,
            "kind": "change_detection_model",
            "golden_id": golden_id,
            **label_metrics(truth, predictions),
        }
        execute(
            con,
            "INSERT INTO model_evaluations VALUES (:id,:name,:gold,:payload,:time)",
            id=str(uuid4()),
            name=name,
            gold=golden_id,
            payload=canonical(report),
            time=now(),
        )
        return report


def export_golden_template(project, golden_id):
    with transaction(project) as con:
        items = rows(con, "SELECT * FROM golden_items WHERE set_id=:id", id=golden_id)
        if not items:
            raise ValueError("Golden set not found")
        template = {
            "golden_id": golden_id,
            "predictions": {i["sample_id"]: dict.fromkeys(KEYS, 0) for i in items},
        }
    path = project.root / "exports" / f"model_predictions_{uuid4().hex}.json"
    path.parent.mkdir(exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(canonical(template))
    return {
        "path": str(path),
        "note": "Replace zero placeholders with actual model predictions before evaluation.",
    }


def import_model_predictions(project, path: Path, name):
    from llm_change_tool.core.labels import strict_json

    if path.stat().st_size > 20_000_000:
        raise ValueError("Prediction file too large")
    data, _ = strict_json(path.read_bytes())
    return model_evaluation(project, data["golden_id"], name, data["predictions"])


def model_comparison(project):
    with transaction(project) as con:
        return [
            json.loads(r["payload"])
            for r in rows(con, "SELECT * FROM model_evaluations ORDER BY created_at")
        ]


def review_report(project, run_id):
    """Per-split/type correction counts and explicitly estimated interaction time."""
    from collections import defaultdict

    from llm_change_tool.core.reviews import review_queue

    items = review_queue(project, run_id)
    with transaction(project) as con:
        effort = one(
            con,
            """SELECT coalesce(sum(e.seconds),0) seconds FROM review_effort e
              JOIN reviews v ON v.revision=e.revision WHERE v.run_id=:run""",
            run=run_id,
        )["seconds"]
        audit = {
            r["sample_id"]
            for r in rows(con, "SELECT sample_id FROM audit_samples WHERE run_id=:run", run=run_id)
        }
        selections = rows(
            con,
            """SELECT p.payload FROM plan_selections p JOIN llm_runs r
                             ON r.plan_id=p.plan_id WHERE r.id=:run""",
            run=run_id,
        )
    groups = defaultdict(lambda: {"total": 0, "completed": 0, "modified": 0})
    done = []
    for item in items:
        group = groups[item["split"] + "/" + (item["error_type"] or "unclassified")]
        group["total"] += 1
        if item["review_state"] == "DONE" and item["review_current"]:
            group["completed"] += 1
            done.append(item)
            group["modified"] += int(
                json.loads(item["reviewed_labels"]) != json.loads(item["original_labels"])
            )
    audited = [s for s in done if s["id"] in audit]
    changed = sum(
        json.loads(s["reviewed_labels"]) != json.loads(s["original_labels"]) for s in done
    )
    audit_changed = sum(
        json.loads(s["reviewed_labels"]) != json.loads(s["original_labels"]) for s in audited
    )
    return {
        "run_id": run_id,
        "completed": len(done),
        "modified": changed,
        "modification_rate": changed / len(done) if done else None,
        "by_error_type": dict(groups),
        "estimated_interaction_seconds": effort,
        "seconds_per_completed": effort / len(done) if done else None,
        "timing_note": "입력 간격 최대 30초만 합산한 추정치. 검수 화면 밖·과거 버전 작업 시간은 포함하지 않습니다.",
        "auto_audit": {
            "selected": len(audit),
            "completed": len(audited),
            "corrected": audit_changed,
            "observed_error_rate": audit_changed / len(audited) if audited else None,
        },
        "selection": json.loads(selections[0]["payload"]) if selections else None,
    }


def export_review_report(project, run_id):
    report = review_report(project, run_id)
    path = project.root / "exports" / ("review-report-" + uuid4().hex + ".json")
    path.write_text(canonical(report), encoding="utf-8")
    return {"path": str(path), **report}
