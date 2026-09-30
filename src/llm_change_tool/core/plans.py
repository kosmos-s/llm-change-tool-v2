import json
from uuid import uuid4

from llm_change_tool.core.datasets import blocking_issues, verify_sources
from llm_change_tool.core.labels import canonical, digest
from llm_change_tool.core.projects import now
from llm_change_tool.core.sampling import (
    balanced_pilot_sample,
    balanced_source_sample,
    selection_report,
)
from llm_change_tool.storage.store import execute, one, rows, transaction


def _select_samples(samples, mode, seed, sample_count):
    if mode == "production":
        selected = []
        for split in ("train", "val", "test"):
            group = [s for s in samples if s["split"] == split]
            if len(group) < 1000:
                raise ValueError(f"{split}: at least 1000 valid samples required")
            selected.extend(balanced_source_sample(group, 1000, seed))
        return selected, selection_report(
            samples, selected, seed, include_source=True, requested_count=3000
        )
    if sample_count is None:
        return samples, None
    if isinstance(sample_count, bool) or not isinstance(sample_count, int) or sample_count <= 0:
        raise ValueError("시험용 표본 수는 1 이상의 정수여야 합니다.")
    selected_count = min(sample_count, len(samples))
    selected = balanced_pilot_sample(samples, selected_count, seed)
    return selected, selection_report(
        samples, selected, seed, include_source=True, requested_count=sample_count
    )


def preview_plan(project, mode="pilot", seed="20260324", sample_count=50):
    if mode not in ("pilot", "production"):
        raise ValueError("Invalid plan mode")
    errors = verify_sources(project, mode)
    if errors:
        raise ValueError(
            f"Dataset quality errors: {len(errors)}; fix sources in a new project if changed"
        )
    with transaction(project) as con:
        samples = rows(con, "SELECT * FROM samples ORDER BY logical_key")
    selected, report = _select_samples(samples, mode, seed, sample_count)
    if not selected:
        raise ValueError("Empty plan")
    return report or selection_report(
        samples, selected, seed, pilot=True, requested_count=len(selected)
    )


def create_plan(project, mode="pilot", seed="20260324", sample_count=None):
    if mode not in ("pilot", "production"):
        raise ValueError("Invalid plan mode")
    errors = verify_sources(project, mode)
    if errors:
        raise ValueError(
            f"Dataset quality errors: {len(errors)}; fix sources in a new project if changed"
        )
    with transaction(project) as con:
        dataset = one(con, "SELECT * FROM datasets")
        samples = rows(con, "SELECT * FROM samples ORDER BY logical_key")
        selected, report = _select_samples(samples, mode, seed, sample_count)
        if not selected:
            raise ValueError("Empty plan")
        ids = sorted(s["id"] for s in selected)
        fp = digest({"dataset": dataset["fingerprint"], "mode": mode, "ids": ids})
        old = rows(con, "SELECT id FROM work_plans WHERE fingerprint=:fp", fp=fp)
        if old:
            return old[0]["id"]
        pid = str(uuid4())
        execute(
            con,
            "INSERT INTO work_plans VALUES (:id,:mode,:ds,:fp,:time)",
            id=pid,
            mode=mode,
            ds=dataset["fingerprint"],
            fp=fp,
            time=now(),
        )
        if report:
            execute(
                con,
                "INSERT INTO plan_selections VALUES (:id,:payload)",
                id=pid,
                payload=canonical(report),
            )
        for sid in ids:
            execute(con, "INSERT INTO work_plan_items VALUES (:pid,:sid)", pid=pid, sid=sid)
        return pid


def validate_plan(con, pid):
    plan = one(con, "SELECT * FROM work_plans WHERE id=:id", id=pid)
    dataset = one(con, "SELECT * FROM datasets")
    members = rows(
        con,
        """SELECT s.* FROM samples s JOIN work_plan_items i ON s.id=i.sample_id
        WHERE i.plan_id=:id ORDER BY s.id""",
        id=pid,
    )
    fp = digest(
        {"dataset": dataset["fingerprint"], "mode": plan["mode"], "ids": [s["id"] for s in members]}
    )
    if not members or fp != plan["fingerprint"] or dataset["fingerprint"] != plan["dataset_hash"]:
        raise ValueError("Stale or invalid work plan")
    if blocking_issues(json.loads(dataset["quality"]), plan["mode"]):
        raise ValueError("Dataset quality errors")
    if plan["mode"] == "production":
        if len(members) != 3000 or any(
            sum(s["split"] == split for s in members) != 1000 for split in ("train", "val", "test")
        ):
            raise ValueError("Production plan must have exactly 1000 samples per split")
    return plan, members
