"""Stable balanced allocation across source, split, error and label strata."""

import json
from collections import Counter, defaultdict

from llm_change_tool.core.labels import digest


def stratum(sample):
    labels = json.loads(sample["original_labels"])
    signature = ",".join(k for k, v in sorted(labels.items()) if v == 1) or "negative"
    if any(v is None for v in labels.values()):
        signature += ",unknown"
    errors = ",".join(sample.get("selection_error_types", [])) or sample["error_type"]
    return errors + ":" + signature


def pilot_stratum(sample):
    return "/".join(
        (sample.get("selection_source", sample["source"]), sample["split"], stratum(sample))
    )


def source_stratum(sample):
    return "/".join((sample.get("selection_source", sample["source"]), stratum(sample)))


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
    if not 0 <= count <= len(samples):
        raise ValueError("Invalid sample count")
    groups = defaultdict(list)
    for sample in samples:
        groups[sample.get("selection_source", sample["source"])].append(sample)
    ordered = [
        _balanced_sample(groups[k], len(groups[k]), seed, stratum)
        for k in sorted(groups, key=lambda k: digest([str(seed), k]))
    ]
    return _interleave(ordered, count)


def _interleave(groups, count):
    result, offset = [], 0
    while len(result) < count:
        for group in groups:
            if offset < len(group):
                result.append(group[offset])
                if len(result) == count:
                    break
        offset += 1
    return result


def balanced_unique_pilot_sample(samples, count, seed):
    """Source first, split second, then label/error strata; capacity-aware."""
    if not 0 <= count <= len(samples):
        raise ValueError("Invalid sample count")
    sources = defaultdict(lambda: defaultdict(list))
    for sample in samples:
        sources[sample.get("selection_source", sample["source"])][sample["split"]].append(sample)
    ordered = []
    for source in sorted(sources, key=lambda k: digest([str(seed), k])):
        splits = sources[source]
        children = [
            _balanced_sample(splits[k], len(splits[k]), seed, stratum)
            for k in sorted(splits, key=lambda k: digest([str(seed), k]))
        ]
        ordered.append(_interleave(children, sum(map(len, children))))
    return _interleave(ordered, count)


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
