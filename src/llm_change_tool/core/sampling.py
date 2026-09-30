"""Stable balanced allocation across source, split, error and label strata."""

import json
from collections import Counter, defaultdict

from llm_change_tool.core.labels import digest


def stratum(sample):
    labels = json.loads(sample["original_labels"])
    signature = ",".join(k for k, v in sorted(labels.items()) if v == 1) or "negative"
    return sample["error_type"] + ":" + signature


def pilot_stratum(sample):
    return "/".join((sample["source"], sample["split"], stratum(sample)))


def source_stratum(sample):
    return "/".join((sample["source"], stratum(sample)))


def _balanced_sample(samples, count, seed, group_key):
    if not 0 <= count <= len(samples):
        raise ValueError("Invalid sample count")
    groups = defaultdict(list)
    for sample in samples:
        groups[group_key(sample)].append(sample)
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


def balanced_sample(samples, count, seed):
    return _balanced_sample(samples, count, seed, stratum)


def balanced_pilot_sample(samples, count, seed):
    return _balanced_sample(samples, count, seed, pilot_stratum)


def balanced_source_sample(samples, count, seed):
    return _balanced_sample(samples, count, seed, source_stratum)


def distribution(samples, *, include_source=False):
    key = (
        pilot_stratum if include_source else lambda sample: sample["split"] + "/" + stratum(sample)
    )
    return dict(sorted(Counter(key(sample) for sample in samples).items()))


def selection_report(samples, selected, seed, *, include_source=False, requested_count=None):
    return {
        "algorithm": (
            "balanced-source-split-error-label-v1" if include_source else "balanced-error-label-v1"
        ),
        "seed": str(seed),
        "candidate_count": len(samples),
        "requested_count": requested_count,
        "selected_count": len(selected),
        "candidates": distribution(samples, include_source=include_source),
        "selected": distribution(selected, include_source=include_source),
        "selected_ids_hash": digest(sorted(s["id"] for s in selected)),
        "note": "Strata are balanced, not population-proportional; do not interpret as population performance.",
    }
