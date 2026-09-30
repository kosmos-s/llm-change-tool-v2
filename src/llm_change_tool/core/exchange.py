"""Bounded ZIP exchange with explicit NEW/SAME/CONFLICT; never auto-overwrite."""

import hashlib
import json
import zipfile
from pathlib import Path
from uuid import uuid4

from llm_change_tool.core.jobs import validate_run
from llm_change_tool.core.labels import (
    SCHEMA_HASH,
    canonical,
    digest,
    strict_json,
    validate_draft,
    validate_labels,
)
from llm_change_tool.core.projects import now
from llm_change_tool.core.reviews import append_review, latest_review
from llm_change_tool.storage.store import execute, one, rows, transaction


def exchange_context(con, run_id):
    run = one(con, "SELECT * FROM llm_runs WHERE id=:id", id=run_id)
    validate_run(con, run)
    plan = one(con, "SELECT * FROM work_plans WHERE id=:id", id=run["plan_id"])
    return {
        "project_fingerprint": digest({"dataset": plan["dataset_hash"], "schema": SCHEMA_HASH}),
        "work_plan_fingerprint": plan["fingerprint"],
        "run_config_hash": run["config_hash"],
    }


def review_payload(review):
    return {
        "labels": json.loads(review["labels"]),
        "reason": review["reason"],
        "reason_en": review["reason_en"],
        "state": review["state"],
        "reviewer": review["reviewer"],
        "timestamp": review["created_at"],
        "result_hash": review["result_hash"],
    }


def same_review(local, payload):
    return bool(local) and all(
        review_payload(local)[k] == payload.get(k)
        for k in ("labels", "reason", "reason_en", "state", "result_hash")
    )


def export_reviews(project, run_id, destination=None):
    package_id = str(uuid4())
    with transaction(project) as con:
        context = exchange_context(con, run_id)
        samples = rows(
            con,
            "SELECT sample_id FROM comparisons WHERE run_id=:run ORDER BY sample_id",
            run=run_id,
        )
        entries = []
        files = {}
        for sample in samples:
            review = latest_review(con, run_id, sample["sample_id"])
            if not review or review["state"] == "DRAFT":
                continue
            payload = review_payload(review)
            payload["sample_id"] = sample["sample_id"]
            name = f"reviews/{sample['sample_id']}.json"
            raw = canonical(payload).encode()
            files[name] = raw
            entries.append(
                {
                    "sample_id": sample["sample_id"],
                    "path": name,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
            )
    if not entries:
        raise ValueError("No completed/deferred reviews to export")
    manifest = {
        "format": "review-batch-v1",
        "id": package_id,
        **context,
        "timestamp": now(),
        "reviews": entries,
    }
    destination = (
        Path(destination)
        if destination
        else project.root / "exports" / f"review_batch_{package_id}.zip"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", canonical(manifest))
        for name, raw in files.items():
            archive.writestr(name, raw)
    return {"path": str(destination), "reviews": len(entries)}


def read_package(path):
    if Path(path).stat().st_size > 50_000_000:
        raise ValueError("ZIP exceeds 50 MB")
    with zipfile.ZipFile(path) as archive:
        info = archive.infolist()
        names = [i.filename for i in info]
        if (
            len(info) > 10001
            or len(names) != len(set(names))
            or sum(i.file_size for i in info) > 100_000_000
        ):
            raise ValueError("ZIP size/count/duplicate limit exceeded")
        if any(i.file_size > 2_000_000 or i.is_dir() or i.flag_bits & 1 for i in info):
            raise ValueError("Unsupported ZIP member")
        manifest_raw = archive.read("manifest.json")
        manifest, _ = strict_json(manifest_raw)
        if manifest.get("format") != "review-batch-v1" or not isinstance(manifest.get("id"), str):
            raise ValueError("Invalid package manifest")
        entries = manifest["reviews"]
        allowed = {"manifest.json"}
        seen = set()
        payloads = []
        for entry in entries:
            sid = entry["sample_id"]
            name = f"reviews/{sid}.json"
            if len(sid) != 64 or any(c not in "0123456789abcdef" for c in sid):
                raise ValueError("Invalid sample ID")
            if entry["path"] != name or name in allowed or sid in seen:
                raise ValueError("Invalid ZIP path/duplicate sample")
            allowed.add(name)
            seen.add(sid)
            raw = archive.read(name)
            if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
                raise ValueError("Review SHA256 mismatch")
            payload, _ = strict_json(raw)
            if payload["sample_id"] != sid:
                raise ValueError("Sample identity mismatch")
            (validate_labels if payload["state"] == "DONE" else validate_draft)(payload["labels"])
            if (
                payload["state"] not in ("DONE", "DEFERRED")
                or not isinstance(payload["reviewer"], str)
                or not payload["reviewer"].strip()
            ):
                raise ValueError("Invalid review")
            if not isinstance(payload["reason"], str) or len(payload["reason"]) > 10000:
                raise ValueError("Invalid reason")
            english = payload.get("reason_en")
            if english is not None and (not isinstance(english, str) or len(english) > 10000):
                raise ValueError("Invalid English reason")
            payloads.append(payload)
        if set(names) != allowed:
            raise ValueError("Unexpected or unsafe ZIP member")
        return manifest, payloads, digest({"manifest": manifest, "payloads": payloads})


def import_reviews(project, run_id, path):
    manifest, payloads, package_hash = read_package(path)
    counts = {"NEW": 0, "SAME": 0, "CONFLICT": 0}
    with transaction(project) as con:
        context = exchange_context(con, run_id)
        if any(manifest[k] != v for k, v in context.items()):
            raise ValueError("Package project/plan/run fingerprint mismatch")
        existing = rows(con, "SELECT * FROM exchange_packages WHERE id=:id", id=manifest["id"])
        if existing:
            if existing[0]["payload_hash"] != package_hash:
                raise ValueError("Package ID reused with different content")
            return {"already_imported": True, **counts}
        for payload in payloads:
            sid = payload["sample_id"]
            comparison = one(
                con,
                "SELECT * FROM comparisons WHERE run_id=:run AND sample_id=:sid",
                run=run_id,
                sid=sid,
            )
            if comparison["result_hash"] != payload["result_hash"]:
                raise ValueError("Review belongs to a different AI/original revision")
            current = latest_review(con, run_id, sid)
            if same_review(current, payload):
                counts["SAME"] += 1
            elif not current:
                append_review(
                    con,
                    run_id,
                    sid,
                    payload["labels"],
                    payload["reason"],
                    payload["reviewer"],
                    payload["state"],
                    None,
                    "zip:" + manifest["id"],
                    reason_en=payload.get("reason_en"),
                )
                counts["NEW"] += 1
            else:
                execute(
                    con,
                    """INSERT INTO merge_conflicts(id,run_id,sample_id,payload,local_revision,package_id)
                    VALUES (:id,:run,:sid,:payload,:rev,:pid)""",
                    id=str(uuid4()),
                    run=run_id,
                    sid=sid,
                    payload=canonical(payload),
                    rev=current["revision"],
                    pid=manifest["id"],
                )
                counts["CONFLICT"] += 1
        execute(
            con,
            "INSERT INTO exchange_packages VALUES (:id,:hash,:time)",
            id=manifest["id"],
            hash=package_hash,
            time=now(),
        )
    return counts


def conflicts(project, run_id):
    with transaction(project) as con:
        result = rows(
            con, "SELECT * FROM merge_conflicts WHERE run_id=:run AND state='OPEN'", run=run_id
        )
        for conflict in result:
            conflict["current"] = latest_review(con, run_id, conflict["sample_id"])
        return result


def resolve_conflict(project, conflict_id, choice, expected_revision):
    if choice not in ("local", "incoming"):
        raise ValueError("Choose local or incoming")
    with transaction(project) as con:
        conflict = one(
            con, "SELECT * FROM merge_conflicts WHERE id=:id AND state='OPEN'", id=conflict_id
        )
        current = latest_review(con, conflict["run_id"], conflict["sample_id"])
        if not current or current["revision"] != expected_revision:
            raise ValueError("Local review changed; reload conflict")
        if choice == "incoming":
            payload = json.loads(conflict["payload"])
            comp = one(
                con,
                "SELECT result_hash FROM comparisons WHERE run_id=:run AND sample_id=:sid",
                run=conflict["run_id"],
                sid=conflict["sample_id"],
            )
            if comp["result_hash"] != payload["result_hash"]:
                raise ValueError("Incoming review is stale")
            append_review(
                con,
                conflict["run_id"],
                conflict["sample_id"],
                payload["labels"],
                payload["reason"],
                payload["reviewer"],
                payload["state"],
                expected_revision,
                "conflict:" + conflict_id,
                reason_en=payload.get("reason_en"),
            )
        execute(
            con,
            "UPDATE merge_conflicts SET state=:state WHERE id=:id",
            state="RESOLVED_" + choice.upper(),
            id=conflict_id,
        )
    return {"resolved": choice}
