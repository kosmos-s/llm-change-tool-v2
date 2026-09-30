"""Stable balanced allocation across error type and original-label strata."""

import json
from collections import Counter, defaultdict

from llm_change_tool.core.labels import digest


def stratum(sample):
    labels = json.loads(sample["original_labels"])
    signature = ",".join(k for k, v in sorted(labels.items()) if v == 1) or "negative"
    return sample["error_type"] + ":" + signature


def balanced_sample(samples, count, seed):
    if not 0 <= count <= len(samples):
        raise ValueError("Invalid sample count")
    groups = defaultdict(list)
    for sample in samples:
        groups[stratum(sample)].append(sample)
    for group in groups.values():
        group.sort(key=lambda s: digest([str(seed), s["id"]]))
    keys = sorted(groups, key=lambda k: digest([str(seed), k]))
    result, offset = [], 0
    while len(result) < count:
        for key in keys:
            if offset < len(groups[key]):
                result.append(groups[key][offset])
                if len(result) == count:
                    break
        offset += 1
    return result


def distribution(samples):
    return dict(sorted(Counter(s["split"] + "/" + stratum(s) for s in samples).items()))


def selection_report(samples, selected, seed):
    return {
        "algorithm": "balanced-error-label-v1",
        "seed": str(seed),
        "candidate_count": len(samples),
        "selected_count": len(selected),
        "candidates": distribution(samples),
        "selected": distribution(selected),
        "selected_ids_hash": digest(sorted(s["id"] for s in selected)),
        "note": "Strata are balanced, not population-proportional; do not interpret as population performance.",
    }
