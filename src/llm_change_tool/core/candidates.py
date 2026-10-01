"""Non-destructive exact-identity preparation for new work plans."""

import json
from collections import Counter, defaultdict
from pathlib import Path

from llm_change_tool.core.datasets import image_content_hash, verify_sources
from llm_change_tool.core.labels import digest, import_labels, strict_json
from llm_change_tool.storage.store import execute, one, rows, transaction

POLICY_VERSION = "unique-candidates-v2"
DEFAULT_TARGETS = {"train": 1000, "val": 1000, "test": 1000}


def targets(value=None):
    value = dict(DEFAULT_TARGETS if value is None else value)
    if (
        set(value) != set(DEFAULT_TARGETS)
        or any(type(n) is not int or n <= 0 for n in value.values())
        or sum(value.values()) != 3000
    ):
        raise ValueError("본작업 목표는 train/val/test의 양수 정수이며 합계 3000이어야 합니다.")
    return value


def prepare_candidates(project):
    errors = verify_sources(project, candidate_policy=True)
    if errors:
        raise ValueError(
            f"Source integrity errors: {len(errors)}; original data or records changed"
        )
    with transaction(project) as con:
        dataset = one(con, "SELECT * FROM datasets")
        samples = rows(con, "SELECT * FROM samples ORDER BY logical_key")
        content = {
            r["sample_id"]: r["content_hash"] for r in rows(con, "SELECT * FROM sample_contents")
        }
    missing = [s for s in samples if s["id"] not in content]
    for sample in missing:
        content[sample["id"]] = image_content_hash(Path(dataset["root"]), sample["paths"])
    if missing:
        with transaction(project) as con:
            for sample in missing:
                execute(
                    con,
                    "INSERT OR IGNORE INTO sample_contents VALUES (:id,:hash)",
                    id=sample["id"],
                    hash=content[sample["id"]],
                )
    return candidate_inventory(samples, content, json.loads(dataset["quality"]))


def candidate_inventory(samples, content, quality):
    groups = defaultdict(list)
    for sample in samples:
        groups[content[sample["id"]]].append(sample)
    eligible, provenance, withheld = [], [], []
    stats = {
        split: dict(
            registered=0,
            unique=0,
            eligible=0,
            duplicate_copies=0,
            held_unique=0,
            rejected=0,
            reason_counts={},
        )
        for split in DEFAULT_TARGETS
    }
    for sample in samples:
        stats[sample["split"]]["registered"] += 1
    known_paths = {json.loads(s["paths"])["json"] for s in samples}
    rejected = []
    for issue in quality:
        if issue.get("path") in known_paths or issue.get("error") in (
            "split_leakage",
            "duplicate_image",
            "source_labels",
        ):
            continue
        unpaired = issue.get("error") == "orphan_image"
        entry = dict(issue, scope="unpaired_image" if unpaired else "sample_excluded")
        if unpaired:
            entry["severity"] = "WARNING"
        rejected.append(entry)
        if not unpaired:
            split = next(
                (p.lower() for p in issue.get("path", "").split("/") if p.lower() in stats), None
            )
            if split:
                stats[split]["rejected"] += 1
                stats[split]["registered"] += 1
    for content_hash, group in sorted(groups.items()):
        group.sort(key=lambda s: s["logical_key"])
        labels = [import_labels(strict_json(s["original_raw"])[0]) for s in group]
        signatures = {digest(label) for label, _ in labels}
        splits = sorted({s["split"] for s in group})
        sources = sorted({s["source"] for s in group})
        reasons = []
        if len(signatures) > 1:
            reasons.append("label_conflict")
        if len(group) > 1 and any(issues for _, issues in labels):
            reasons.append("incomplete_duplicate_labels")
        if len(splits) > 1:
            reasons.append("split_leakage")
        entry = dict(
            content_hash=content_hash,
            representative_id=group[0]["id"],
            member_ids=[s["id"] for s in group],
            logical_keys=[s["logical_key"] for s in group],
            sources=sources,
            splits=splits,
            error_types=sorted({s["error_type"] for s in group if s["error_type"]}),
            status="held" if reasons else "eligible",
            reasons=reasons,
            review_required=any(issues for _, issues in labels),
        )
        provenance.append(entry)
        for split in splits:
            stat = stats[split]
            stat["unique"] += 1
            stat["duplicate_copies"] += sum(s["split"] == split for s in group) - 1
            if reasons:
                stat["held_unique"] += 1
                for reason in reasons:
                    stat["reason_counts"][reason] = stat["reason_counts"].get(reason, 0) + 1
            else:
                stat["eligible"] += 1
        if reasons:
            withheld.append(entry)
        else:
            representative = dict(group[0])
            representative["selection_source"] = "+".join(sources)
            representative["selection_error_types"] = entry["error_types"]
            eligible.append(representative)
    return eligible, dict(
        policy_version=POLICY_VERSION,
        identity="decoded-RGB-exact-v1",
        representative_policy="lexical-logical-key-after-label-agreement",
        registered_count=len(samples) + sum(s["rejected"] for s in stats.values()),
        valid_registered_count=len(samples),
        unique_count=len(groups),
        content_index_hash=digest(sorted(content.items())),
        duplicate_copies=len(samples) - len(groups),
        eligible_count=len(eligible),
        held_unique_count=len(withheld),
        split_counts=stats,
        rejected=rejected,
        groups=provenance,
        held_reason_counts=dict(Counter(r for g in withheld for r in g["reasons"])),
        source_groups=dict(Counter("+".join(g["sources"]) for g in provenance)),
        reason_note="Reason counts may overlap; held_unique_count does not double count.",
        label_policy_note="FN/FP folders are provenance only, never ground-truth labels.",
    )
