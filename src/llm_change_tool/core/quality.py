"""Read-only quality inspection and explicit, audited preparation of a new dataset."""

import json
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from uuid import uuid4

from llm_change_tool.core.datasets import (
    quality_issues,
    safe_path,
    scan_dataset,
    sha,
    verify_sources,
)
from llm_change_tool.core.jobs import validate_run
from llm_change_tool.core.labels import canonical, digest, effective_doc, import_labels, strict_json
from llm_change_tool.core.locking import worker_lock
from llm_change_tool.core.projects import now
from llm_change_tool.core.reviews import latest_review, result_binding
from llm_change_tool.storage.store import execute, one, rows, transaction


def image_identity(sample):
    hashes = json.loads(sample["hashes"])
    return digest([hashes.get("t1"), hashes.get("t2")]) if "t1" in hashes else hashes["combined"]


def quality_report(project, run_id=None, mode="pilot"):
    with transaction(project) as con:
        dataset = one(con, "SELECT * FROM datasets")
        samples = rows(con, "SELECT * FROM samples ORDER BY logical_key")
        excluded = (
            {
                r["sample_id"]: r["reason"]
                for r in rows(
                    con, "SELECT * FROM preparation_exclusions WHERE run_id=:run", run=run_id
                )
            }
            if run_id
            else {}
        )
        by_path, groups = {}, defaultdict(list)
        for sample in samples:
            review = latest_review(con, run_id, sample["id"]) if run_id else None
            sample["final_labels"] = json.loads(review["labels"]) if review else None
            sample["review_state"] = review["state"] if review else None
            sample["excluded"] = excluded.get(sample["id"])
            sample["original_labels"] = json.loads(sample["original_labels"])
            by_path[json.loads(sample["paths"])["json"]] = sample
            groups[image_identity(sample)].append(sample)
        issues = quality_issues(json.loads(dataset["quality"]), mode)
        for issue in issues:
            sample = by_path.get(issue.get("path"))
            issue["sample_id"] = sample["id"] if sample else None
            issue["status"] = (
                "원본 문제"
                if not sample
                else (
                    "준비 제외 예정"
                    if sample["excluded"]
                    else "수정 검수 완료·복사본 재검사 필요"
                    if sample["review_state"] == "DONE" and issue["error"] == "source_labels"
                    else "미해결"
                )
            )
        # Do not include source JSON bytes in reports.
        visible = [
            {
                k: s[k]
                for k in (
                    "id",
                    "logical_key",
                    "split",
                    "original_labels",
                    "final_labels",
                    "review_state",
                    "excluded",
                )
            }
            for s in samples
        ]
        lookup = {s["id"]: s for s in visible}
        duplicates = [
            [lookup[s["id"]] for s in group] for group in groups.values() if len(group) > 1
        ]
        return {
            "mode": mode,
            "issues": issues,
            "samples": visible,
            "duplicates": duplicates,
            "fatal": sum(i["severity"] == "FATAL" for i in issues),
            "warnings": sum(i["severity"] == "WARNING" for i in issues),
        }


def set_exclusion(project, run_id, sample_id, reason=None):
    with transaction(project) as con:
        one(
            con,
            """SELECT i.sample_id FROM job_items i JOIN jobs j ON j.id=i.job_id
                    WHERE j.run_id=:run AND i.sample_id=:sid""",
            run=run_id,
            sid=sample_id,
        )
        if reason is not None and (not reason.strip() or len(reason) > 2000):
            raise ValueError("제외 사유를 1~2000자로 입력하세요.")
        if reason is None:
            execute(
                con,
                "DELETE FROM preparation_exclusions WHERE run_id=:run AND sample_id=:sid",
                run=run_id,
                sid=sample_id,
            )
        else:
            execute(
                con,
                """INSERT INTO preparation_exclusions VALUES (:run,:sid,:reason,:time)
                           ON CONFLICT(run_id,sample_id) DO UPDATE SET reason=:reason,created_at=:time""",
                run=run_id,
                sid=sample_id,
                reason=reason.strip(),
                time=now(),
            )
        execute(
            con,
            "INSERT INTO quality_events(run_id,sample_id,action,reason,created_at) VALUES (:run,:sid,:action,:reason,:time)",
            run=run_id,
            sid=sample_id,
            action="include" if reason is None else "exclude",
            reason=reason or "",
            time=now(),
        )
    return {"sample_id": sample_id, "excluded": reason is not None}


def preparation_preview(project, run_id):
    """Resolve final labels without weakening the normal export gate."""
    fatal = verify_sources(project, "pilot")
    if fatal:
        raise ValueError("파일 무결성/파싱 오류를 먼저 해결하세요: " + str(fatal[:3]))
    with transaction(project) as con:
        run = one(con, "SELECT * FROM llm_runs WHERE id=:id", id=run_id)
        validate_run(con, run)
        job = one(con, "SELECT * FROM jobs WHERE run_id=:run", run=run_id)
        if job["state"] == "RUNNING":
            raise ValueError("분석을 멈춘 뒤 준비하세요.")
        dataset = one(con, "SELECT * FROM datasets")
        samples = rows(
            con,
            """SELECT s.*, i.state item_state, i.error, r.prediction,
            c.required,c.decision,c.result_hash FROM samples s
            JOIN job_items i ON i.sample_id=s.id AND i.job_id=:job
            LEFT JOIN llm_results r ON r.sample_id=s.id AND r.run_id=:run
            LEFT JOIN comparisons c ON c.sample_id=s.id AND c.run_id=:run ORDER BY s.logical_key""",
            job=job["id"],
            run=run_id,
        )
        excluded = rows(con, "SELECT * FROM preparation_exclusions WHERE run_id=:run", run=run_id)
        excluded_ids = {e["sample_id"] for e in excluded}
        included, problems, identities = [], [], set()
        for sample in samples:
            if sample["id"] in excluded_ids:
                continue
            name = sample["logical_key"]
            binding = result_binding(sample, sample["prediction"], sample["error"])
            if (
                sample["item_state"] != "COMPLETED"
                or not sample["prediction"]
                or binding != sample["result_hash"]
            ):
                problems.append(name + ": 분석/비교 미완료")
                continue
            if rows(
                con,
                "SELECT id FROM merge_conflicts WHERE run_id=:run AND sample_id=:sid AND state='OPEN'",
                run=run_id,
                sid=sample["id"],
            ):
                problems.append(name + ": 팀 충돌 미해결")
                continue
            review = latest_review(con, run_id, sample["id"])
            issues = import_labels(strict_json(sample["original_raw"])[0])[1]
            if review:
                if review["state"] != "DONE" or review["result_hash"] != binding:
                    problems.append(name + ": 검수 미완료")
                    continue
                labels = json.loads(review["labels"])
                reason, english = review["reason"], review["reason_en"]
            elif sample["required"] or sample["decision"] != "AUTO_KEEP" or issues:
                problems.append(name + ": 필수 검수 미완료")
                continue
            else:
                labels = json.loads(sample["original_labels"])
                reason = ""
                english = None
            try:
                doc = effective_doc(sample["original_raw"], labels, reason, english)
            except ValueError as exc:
                problems.append(name + ": " + str(exc))
                continue
            identity = image_identity(sample)
            if identity in identities:
                problems.append(name + ": 중복 그룹에서 대표 항목 외에는 명시적으로 제외하세요.")
            identities.add(identity)
            included.append((sample, doc, review["revision"] if review else None))
        if not included:
            problems.append("포함할 데이터가 없습니다.")
        counts = Counter(s["split"] for s, _, _ in included if s["source"] == "errors")
        report = {
            "included": len(included),
            "excluded": len(excluded),
            "split_counts": dict(counts),
            "problems": problems,
            "ready": not problems,
            "production_size_ready": all(counts[s] >= 1000 for s in ("train", "val", "test")),
            "note": "새 데이터셋은 원본과 별개입니다. 본작업 자격은 새 프로젝트에서 다시 검사합니다.",
        }
        return report, included, excluded, dataset, run


def prepare_dataset(project, run_id, destination: Path):
    with worker_lock(project):
        report, included, excluded, dataset, run = preparation_preview(project, run_id)
        if not report["ready"]:
            raise ValueError("데이터 준비 차단: " + "; ".join(report["problems"][:8]))
        destination = Path(destination).resolve()
        source = Path(dataset["root"]).resolve()
        for protected in (source, project.root.resolve()):
            if destination.is_relative_to(protected) or protected.is_relative_to(destination):
                raise ValueError("원본·프로젝트와 겹치지 않는 새 폴더를 선택하세요.")
        if destination.exists():
            raise FileExistsError(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        stage = destination.parent / (".prepare-" + uuid4().hex)
        stage.mkdir()
        published = False
        try:
            data = stage / "dataset"
            data.mkdir()
            manifest_items = []
            for sample, doc, revision in included:
                paths = json.loads(sample["paths"])
                hashes = json.loads(sample["hashes"])
                outputs = {}
                for role, rel in paths.items():
                    target = safe_path(data, rel)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if sha(safe_path(source, rel)) != hashes[role]:
                        raise ValueError("Source changed during preparation")
                    if role == "json":
                        target.write_text(canonical(doc) + "\n", encoding="utf-8")
                    else:
                        shutil.copyfile(safe_path(source, rel), target)
                        if sha(target) != hashes[role]:
                            raise ValueError("Source changed during preparation")
                    outputs[rel] = sha(target)
                manifest_items.append(
                    {
                        "sample_id": sample["id"],
                        "source_hashes": hashes,
                        "output_hashes": outputs,
                        "review_revision": revision,
                    }
                )
            _, errors, fingerprint = scan_dataset(data)
            if errors:
                raise ValueError("생성 데이터 재검사 실패: " + str(errors[:5]))
            manifest = {
                "id": uuid4().hex,
                "kind": "prepared-dataset-v1",
                "source_fingerprint": dataset["fingerprint"],
                "run_id": run_id,
                "run_config_hash": run["config_hash"],
                "output_fingerprint": fingerprint,
                "created_at": now(),
                "summary": report,
                "excluded": excluded,
                "included": manifest_items,
            }
            (stage / "preparation-manifest.json").write_text(canonical(manifest), encoding="utf-8")
            with transaction(project) as con:
                execute(
                    con,
                    "INSERT INTO preparation_history VALUES (:id,:run,:manifest,:time)",
                    id=manifest["id"],
                    run=run_id,
                    manifest=canonical(manifest),
                    time=now(),
                )
                if destination.exists():
                    raise FileExistsError(destination)
                stage.rename(destination)
                published = True
            return {
                "path": str(destination / "dataset"),
                "manifest": str(destination / "preparation-manifest.json"),
                **report,
            }
        except Exception:
            if published:
                shutil.rmtree(destination, ignore_errors=True)
            shutil.rmtree(stage, ignore_errors=True)
            raise
