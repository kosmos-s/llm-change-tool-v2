"""Run-scoped compare decisions and append-only human revisions."""

import json

from llm_change_tool.core.jobs import validate_run
from llm_change_tool.core.labels import (
    KEYS,
    Prediction,
    canonical,
    digest,
    effective_doc,
    validate_labels,
)
from llm_change_tool.core.projects import now
from llm_change_tool.storage.store import execute, one, rows, transaction


def result_binding(sample, result, error):
    return digest({"original": sample["hashes"], "prediction": result, "error": error})


def compare_run(project, run_id):
    with transaction(project) as con:
        run = one(con, "SELECT * FROM llm_runs WHERE id=:id", id=run_id)
        config = validate_run(con, run)
        items = rows(
            con,
            """SELECT s.*, i.error, i.state item_state,r.prediction FROM samples s
            JOIN job_items i ON i.sample_id=s.id JOIN jobs j ON j.id=i.job_id
            LEFT JOIN llm_results r ON r.sample_id=s.id AND r.run_id=j.run_id
            WHERE j.run_id=:run""",
            run=run_id,
        )
        required = 0
        for sample in items:
            signals = []
            prediction = sample["prediction"]
            if not prediction:
                signals.append(
                    "malformed_output"
                    if sample["error"] == "malformed_output"
                    else "API_error"
                    if sample["error"]
                    else "pending"
                )
            else:
                try:
                    p = Prediction.model_validate_json(prediction)
                    original = json.loads(sample["original_labels"])
                    if bool(any(original.values())) != bool(any(p.labels.values())):
                        signals.append("change_mismatch")
                    if any(original[k] != p.labels[k] for k in KEYS):
                        signals.append("detail_mismatch")
                    if p.confidence < config.confidence_threshold:
                        signals.append("low_confidence")
                    if p.review_required:
                        signals.append("review_required")
                except ValueError:
                    signals.append("malformed_output")
            # core records low confidence but it alone does not force review (v1 policy).
            needed = bool(
                [s for s in signals if s != "low_confidence" or config.review_policy == "detailed"]
            )
            required += needed
            binding = result_binding(sample, prediction, sample["error"])
            execute(
                con,
                """INSERT INTO comparisons VALUES (:run,:sid,:hash,:signals,:required,:decision)
                ON CONFLICT(run_id,sample_id) DO UPDATE SET result_hash=:hash,signals=:signals,
                required=:required,decision=:decision""",
                run=run_id,
                sid=sample["id"],
                hash=binding,
                signals=canonical(signals),
                required=int(needed),
                decision="REVIEW" if needed else "AUTO_KEEP",
            )
        return {"compared": len(items), "required": required}


def latest_review(con, run_id, sample_id):
    result = rows(
        con,
        """SELECT * FROM reviews WHERE run_id=:run AND sample_id=:sid
        ORDER BY revision DESC LIMIT 1""",
        run=run_id,
        sid=sample_id,
    )
    return result[0] if result else None


def append_review(
    con,
    run_id,
    sample_id,
    labels,
    reason,
    reviewer,
    state="DONE",
    expected_revision=None,
    origin="local",
    reason_en=None,
):
    if state not in ("DONE", "DEFERRED", "DRAFT"):
        raise ValueError("Invalid review state")
    validate_labels(labels)
    if not reviewer.strip() or len(reviewer) > 120:
        raise ValueError("Reviewer name is required (max 120 chars)")
    if len(reason) > 10000:
        raise ValueError("Reason too long")
    if reason_en is not None and (not isinstance(reason_en, str) or len(reason_en) > 10000):
        raise ValueError("영문 근거는 최대 10,000자입니다.")
    if state == "DONE":
        sample = one(con, "SELECT original_raw FROM samples WHERE id=:id", id=sample_id)
        effective_doc(sample["original_raw"], labels, reason, reason_en)
    comparison = one(
        con,
        "SELECT * FROM comparisons WHERE run_id=:run AND sample_id=:sid",
        run=run_id,
        sid=sample_id,
    )
    latest = latest_review(con, run_id, sample_id)
    current = latest["revision"] if latest else None
    if current != expected_revision:
        raise ValueError("Review changed since loading. Reload before saving.")
    result = execute(
        con,
        """INSERT INTO reviews(sample_id,run_id,state,labels,reason,reviewer,
        previous_revision,result_hash,origin,created_at,reason_en)
        VALUES (:sid,:run,:state,:labels,:reason,:reviewer,:prev,:hash,:origin,:time,:english)""",
        sid=sample_id,
        run=run_id,
        state=state,
        labels=canonical(labels),
        reason=reason,
        reviewer=reviewer.strip(),
        prev=current,
        hash=comparison["result_hash"],
        origin=origin,
        time=now(),
        english=reason_en,
    )
    return result.lastrowid


def save_review(
    project,
    run_id,
    sample_id,
    labels,
    reason,
    reviewer,
    state="DONE",
    expected_revision=None,
    reason_en=None,
):
    with transaction(project) as con:
        return append_review(
            con,
            run_id,
            sample_id,
            labels,
            reason,
            reviewer,
            state,
            expected_revision,
            reason_en=reason_en,
        )


def _represented_review(con, review):
    """Resolve an audit entry to the historical state it restored, including v2 undo."""
    while review:
        target = rows(
            con,
            "SELECT target_revision FROM review_undo_targets WHERE revision=:id",
            id=review["revision"],
        )
        if target:
            revision = target[0]["target_revision"]
        elif review["origin"] == "undo":
            # v2 undo restored the state before the revision it appended to.
            previous = one(
                con, "SELECT * FROM reviews WHERE revision=:id", id=review["previous_revision"]
            )
            revision = previous["previous_revision"]
        else:
            return review
        review = (
            one(con, "SELECT * FROM reviews WHERE revision=:id", id=revision) if revision else None
        )
    return None


def undo_review(project, run_id, sample_id, reviewer, expected_revision=None):
    with transaction(project) as con:
        current = latest_review(con, run_id, sample_id)
        if not current:
            raise ValueError("No review to undo")
        if expected_revision is not None and current["revision"] != expected_revision:
            raise ValueError("Review changed since loading. Reload before saving.")
        represented = _represented_review(con, current)
        if not represented:
            raise ValueError("원본까지 되돌렸습니다. 더 이전 기록이 없습니다.")
        previous = (
            _represented_review(
                con,
                one(
                    con,
                    "SELECT * FROM reviews WHERE revision=:id",
                    id=represented["previous_revision"],
                ),
            )
            if represented["previous_revision"]
            else None
        )
        if previous:
            labels = json.loads(previous["labels"])
            reason = previous["reason"]
            state = previous["state"]
            reason_en = previous["reason_en"]
        else:
            sample = one(con, "SELECT * FROM samples WHERE id=:id", id=sample_id)
            labels = json.loads(sample["original_labels"])
            reason = "Undo to original"
            state = "DRAFT"
            reason_en = None
            # Preserve excluded legacy labels in original, but new drafts follow the current policy.
            from llm_change_tool.core.labels import FIELDS

            for f in FIELDS:
                if "fixed" in f:
                    labels[f["key"]] = f["fixed"]
        revision = append_review(
            con,
            run_id,
            sample_id,
            labels,
            reason,
            reviewer,
            state,
            current["revision"],
            "undo",
            reason_en=reason_en,
        )
        execute(
            con,
            "INSERT INTO review_undo_targets VALUES (:id,:target)",
            id=revision,
            target=previous["revision"] if previous else None,
        )
        return revision


def review_queue(project, run_id, filter_name="all"):
    with transaction(project) as con:
        result = rows(
            con,
            """SELECT s.*,c.required,c.signals,c.result_hash,r.prediction,
            v.state review_state,v.revision,v.labels reviewed_labels,v.reason reviewed_reason,v.reason_en reviewed_reason_en,v.reviewer,
            coalesce(v.result_hash=c.result_hash,0) review_current
            FROM samples s JOIN comparisons c ON c.sample_id=s.id AND c.run_id=:run
            LEFT JOIN llm_results r ON r.sample_id=s.id AND r.run_id=:run
            LEFT JOIN reviews v ON v.revision=(SELECT max(revision) FROM reviews
                WHERE run_id=:run AND sample_id=s.id)
            ORDER BY s.logical_key""",
            run=run_id,
        )
    if filter_name == "unreviewed":
        return [
            s
            for s in result
            if not s["review_current"] or s["review_state"] not in ("DONE", "DEFERRED")
        ]
    if filter_name == "deferred":
        return [s for s in result if s["review_state"] == "DEFERRED"]
    if filter_name == "required":
        return [
            s
            for s in result
            if s["required"] and (s["review_state"] != "DONE" or not s["review_current"])
        ]
    return result


def review_summary(project, run_id):
    """Count the whole run, independently of the visible review filter."""
    with transaction(project) as con:
        return one(
            con,
            """SELECT count(*) total,
            coalesce(sum(CASE WHEN c.required=1 AND NOT (coalesce(v.state,'')='DONE' AND coalesce(v.result_hash,'')=c.result_hash) THEN 1 ELSE 0 END),0) required_remaining,
            coalesce(sum(CASE WHEN v.state='DONE' AND v.result_hash=c.result_hash THEN 1 ELSE 0 END),0) completed,
            coalesce(sum(CASE WHEN v.state='DEFERRED' THEN 1 ELSE 0 END),0) deferred
            FROM comparisons c LEFT JOIN reviews v ON v.revision=(SELECT max(revision)
            FROM reviews WHERE run_id=c.run_id AND sample_id=c.sample_id)
            WHERE c.run_id=:run""",
            run=run_id,
        )


def review_history(project, run_id, sample_id):
    with transaction(project) as con:
        return rows(
            con,
            "SELECT * FROM reviews WHERE run_id=:run AND sample_id=:sid ORDER BY revision",
            run=run_id,
            sid=sample_id,
        )
