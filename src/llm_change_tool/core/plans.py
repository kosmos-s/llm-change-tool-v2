"""Frozen plans; existing plans retain their original validation contract."""

import json
from uuid import uuid4

from llm_change_tool.core.candidates import POLICY_VERSION, prepare_candidates, targets
from llm_change_tool.core.datasets import blocking_issues, verify_sources
from llm_change_tool.core.labels import canonical, digest
from llm_change_tool.core.projects import now
from llm_change_tool.core.sampling import (
    balanced_pilot_sample,
    balanced_source_sample,
    balanced_unique_pilot_sample,
    selection_report,
)
from llm_change_tool.storage.store import execute, has_table, one, rows, transaction


def _select_samples(samples, mode, seed, sample_count, split_targets=None, *, preview=False):
    if mode == "production":
        goals = targets(split_targets)
        selected, shortages = [], {}
        for split, goal in goals.items():
            group = [s for s in samples if s["split"] == split]
            if len(group) < goal:
                shortages[split] = goal - len(group)
            selected.extend(balanced_source_sample(group, min(goal, len(group)), seed))
        if shortages and not preview:
            raise ValueError(
                f"Dataset quality / insufficient unique candidates: targets={goals}; shortage={shortages}"
            )
        report = selection_report(
            samples, selected, seed, include_source=True, requested_count=3000
        )
        report.update(
            split_targets=goals,
            shortages=shortages,
            ready=not shortages,
            source_policy="equal-source-buckets-capacity-redistributed-v2",
        )
        return selected, report
    if sample_count is None:
        return samples, selection_report(
            samples, samples, seed, include_source=True, requested_count=len(samples)
        )
    if type(sample_count) is not int or sample_count <= 0:
        raise ValueError("시험용 표본 수는 1 이상의 정수여야 합니다.")
    selected = balanced_pilot_sample(samples, min(sample_count, len(samples)), seed)
    return selected, selection_report(
        samples, selected, seed, include_source=True, requested_count=sample_count
    )


def _selection(
    project, mode, seed, sample_count, split_targets, candidate_policy, *, preview=False
):
    if mode not in ("pilot", "production"):
        raise ValueError("Invalid plan mode")
    use_candidates = mode == "production" or candidate_policy
    if use_candidates:
        samples, inventory = prepare_candidates(project)
    else:
        if errors := verify_sources(project, mode):
            raise ValueError(
                f"Dataset quality errors: {len(errors)}; fix sources in a new project if changed"
            )
        with transaction(project) as con:
            samples = rows(con, "SELECT * FROM samples ORDER BY logical_key")
        inventory = None
    try:
        selected, report = _select_samples(
            samples, mode, seed, sample_count, split_targets, preview=preview
        )
    except ValueError as exc:
        if inventory is not None and "insufficient unique" in str(exc):
            raise ValueError(
                f"{exc}; split candidate counts and hold reasons={inventory['split_counts']}"
            ) from exc
        raise
    if not selected and not preview:
        raise ValueError("Empty plan")
    if inventory is not None:
        if mode == "pilot":
            selected = balanced_unique_pilot_sample(samples, len(selected), seed)
            report = selection_report(
                samples,
                selected,
                seed,
                include_source=True,
                requested_count=sample_count if sample_count is not None else len(samples),
            )
        report.update(
            policy_version=POLICY_VERSION,
            inventory=inventory,
            algorithm="hierarchical-source-error-label-v2"
            if mode == "production"
            else "unique-pilot-strata-v2",
        )
        report["selected_ids"] = sorted(s["id"] for s in selected)
        report["candidate_ids_hash"] = digest(sorted(s["id"] for s in samples))
        for split, stat in inventory["split_counts"].items():
            goal = report.get("split_targets", {}).get(split)
            stat["target"] = goal
            stat["shortage"] = max(0, goal - stat["eligible"]) if goal is not None else None
    return selected, report, use_candidates


def preview_plan(
    project,
    mode="pilot",
    seed="20260324",
    sample_count=50,
    *,
    split_targets=None,
    candidate_policy=False,
):
    return _selection(
        project, mode, seed, sample_count, split_targets, candidate_policy, preview=True
    )[1]


def create_plan(
    project,
    mode="pilot",
    seed="20260324",
    sample_count=None,
    *,
    split_targets=None,
    candidate_policy=False,
):
    selected, report, use_candidates = _selection(
        project, mode, seed, sample_count, split_targets, candidate_policy
    )
    with transaction(project) as con:
        dataset = one(con, "SELECT * FROM datasets")
        ids = sorted(s["id"] for s in selected)
        binding = {"dataset": dataset["fingerprint"], "mode": mode, "ids": ids}
        if use_candidates:
            binding["selection"] = digest(report)
        fp = digest(binding)
        if old := rows(con, "SELECT id FROM work_plans WHERE fingerprint=:fp", fp=fp):
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
        if has_table(con, "plan_selections"):
            execute(
                con,
                "INSERT INTO plan_selections VALUES (:id,:payload)",
                id=pid,
                payload=canonical(report),
            )
        if use_candidates:
            execute(
                con, "INSERT INTO plan_policies VALUES (:id,:hash)", id=pid, hash=digest(report)
            )
        for sid in ids:
            execute(con, "INSERT INTO work_plan_items VALUES (:pid,:sid)", pid=pid, sid=sid)
        return pid


def plan_uses_candidates(con, pid):
    return has_table(con, "plan_policies") and bool(
        rows(con, "SELECT plan_id FROM plan_policies WHERE plan_id=:id", id=pid)
    )


def validate_plan(con, pid):
    plan = one(con, "SELECT * FROM work_plans WHERE id=:id", id=pid)
    dataset = one(con, "SELECT * FROM datasets")
    members = rows(
        con,
        """SELECT s.* FROM samples s JOIN work_plan_items i ON s.id=i.sample_id
    WHERE i.plan_id=:id ORDER BY s.id""",
        id=pid,
    )
    binding = {
        "dataset": dataset["fingerprint"],
        "mode": plan["mode"],
        "ids": [s["id"] for s in members],
    }
    policy = (
        rows(con, "SELECT * FROM plan_policies WHERE plan_id=:id", id=pid)
        if has_table(con, "plan_policies")
        else []
    )
    report = None
    if policy:
        report = json.loads(
            one(con, "SELECT payload FROM plan_selections WHERE plan_id=:id", id=pid)["payload"]
        )
        if (
            report.get("policy_version") != POLICY_VERSION
            or digest(report) != policy[0]["policy_hash"]
        ):
            raise ValueError("Stale or invalid work plan selection policy")
        content = rows(con, "SELECT sample_id,content_hash FROM sample_contents ORDER BY sample_id")
        if (
            digest([(r["sample_id"], r["content_hash"]) for r in content])
            != report["inventory"]["content_index_hash"]
        ):
            raise ValueError("Stale or invalid work plan content index")
        if sorted(report["selected_ids"]) != binding["ids"]:
            raise ValueError("Stale or invalid work plan selection IDs")
        eligible = {
            g["representative_id"]
            for g in report["inventory"]["groups"]
            if g["status"] == "eligible"
        }
        if not set(binding["ids"]).issubset(eligible):
            raise ValueError("Work plan contains held candidates")
        binding["selection"] = digest(report)
    if (
        not members
        or digest(binding) != plan["fingerprint"]
        or dataset["fingerprint"] != plan["dataset_hash"]
    ):
        raise ValueError("Stale or invalid work plan")
    if not policy and blocking_issues(json.loads(dataset["quality"]), plan["mode"]):
        raise ValueError("Dataset quality errors")
    if plan["mode"] == "production":
        goals = targets(report["split_targets"] if report else None)
        if len(members) != 3000 or any(
            sum(s["split"] == split for s in members) != goal for split, goal in goals.items()
        ):
            raise ValueError(
                "Production plan must match frozen split targets (default 1000 per split)"
            )
    return plan, members
