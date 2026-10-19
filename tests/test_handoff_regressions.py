"""Offline reproductions of the 2026-10-15 handoff findings."""

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from llm_change_tool.core.datasets import import_dataset
from llm_change_tool.core.exporting import export_run, final_gate
from llm_change_tool.core.jobs import RunConfig, create_job, run_job, validate_run
from llm_change_tool.core.labels import KEYS, SCHEMA_HASH, canonical, digest, effective_doc
from llm_change_tool.core.plans import create_plan
from llm_change_tool.core.projects import (
    backup_project,
    create_project,
    open_project,
    restore_project,
)
from llm_change_tool.core.reviews import (
    compare_run,
    low_confidence_required,
    review_queue,
    review_summary,
    save_review,
)
from llm_change_tool.providers.base import ProviderResponse
from llm_change_tool.storage.store import execute, one, rows, transaction


class Matching:
    def __init__(self, confidence=0.1):
        self.confidence = confidence

    def predict(self, images, prompt, config):
        return ProviderResponse(
            json.dumps(
                dict(
                    labels=dict.fromkeys(KEYS, 0),
                    confidence=self.confidence,
                    reason="합성 판정",
                    review_required=False,
                )
            ),
            10,
            10,
        )


def test_cleared_other_removes_effective_description(imported):
    project, _ = imported
    with transaction(project, readonly=True) as con:
        raw = rows(con, "SELECT original_raw FROM samples LIMIT 1")[0]["original_raw"]
    doc = json.loads(raw)
    doc["artifact_detail"]["arti_other"] = "o"
    doc["Artifact"] = "o"
    doc["artifact_detail"]["arti_other_detail"] = "이전 기타 설명"
    raw = json.dumps(doc).encode()
    active = dict.fromkeys(KEYS, 0)
    active["arti"] = active["arti_other"] = 1
    assert (
        effective_doc(raw, active, "")["artifact_detail"]["arti_other_detail"]
        == doc["artifact_detail"]["arti_other_detail"]
    )
    result = effective_doc(raw, dict.fromkeys(KEYS, 0), "기타 변화 없음")
    assert result["artifact_detail"]["arti_other_detail"] == ""
    assert json.loads(raw) == doc
    del doc["artifact_detail"]["arti_other_detail"]
    assert (
        "arti_other_detail"
        not in effective_doc(json.dumps(doc).encode(), dict.fromkeys(KEYS, 0), "No other change")[
            "artifact_detail"
        ]
    )


def test_default_low_confidence_matching_labels_need_review(imported):
    project, _ = imported
    job = create_job(project, create_plan(project), RunConfig())
    result = run_job(project, job, provider=Matching())
    run = result["run_id"]
    assert compare_run(project, run)["required"] == 6
    assert len(review_queue(project, run, "required")) == 6
    assert review_summary(project, run)["required_remaining"] == 6
    assert not final_gate(project, run)["passed"]


def test_large_images_reserve_more_than_fixed_20000(imported, monkeypatch):
    project, _ = imported
    monkeypatch.setattr(
        "llm_change_tool.core.jobs.sample_images", lambda *a: [Image.new("RGB", (2048, 2048))] * 2
    )
    config = RunConfig(provider="openai", input_price=0.15, output_price=0.60)
    fixed = config.reserve()

    class Inspect(Matching):
        def predict(self, images, prompt, config):
            with transaction(project, readonly=True) as con:
                attempt = rows(con, "SELECT reserved_cost FROM attempts WHERE state='RUNNING'")[0]
            assert attempt["reserved_cost"] > fixed
            return super().predict(images, prompt, config)

    job = create_job(project, create_plan(project), config)
    result = run_job(project, job, provider=Inspect())
    assert result["state"] == "COMPLETED"


def test_legacy_core_pilot_preserves_frozen_settings_and_warns(imported):
    project, _ = imported
    job = create_job(project, create_plan(project), RunConfig(review_policy="core"))
    # Reproduce a genuine 0.1.10 config with no newly introduced fields.
    with transaction(project) as con:
        run = one(con, "SELECT * FROM llm_runs")
        config = json.loads(run["config"])
        del config["image_detail"], config["image_token_override"]
        frozen_hash = digest(dict(config=config, prompt=run["prompt"], schema=SCHEMA_HASH))
        execute(
            con,
            "UPDATE llm_runs SET config=:config,config_hash=:hash",
            config=canonical(config),
            hash=frozen_hash,
        )
        assert validate_run(con, one(con, "SELECT * FROM llm_runs")).review_policy == "core"
    assert run_job(open_project(project.root), job, provider=Matching())["state"] == "COMPLETED"
    assert compare_run(project, run["id"])["required"] == 0
    assert not review_queue(project, run["id"], "required")
    report = final_gate(project, run["id"])
    assert report["passed"] and report["legacy_core_pilot"]
    assert report["counts"]["human_complete"] == 0 and not report["all_human_reviewed"]
    with transaction(project, readonly=True) as con:
        assert one(con, "SELECT config_hash FROM llm_runs")["config_hash"] == frozen_hash


@pytest.mark.parametrize("policy", ["core", "detailed"])
def test_production_low_confidence_floor_in_queue_counts_and_gate(imported, monkeypatch, policy):
    project, _ = imported
    config = RunConfig(provider="openai", input_price=0.15, output_price=0.6, review_policy=policy)
    assert low_confidence_required(config, "production")
    job = create_job(project, create_plan(project), config)
    run = run_job(project, job, provider=Matching())["run_id"]
    compare_run(project, run)
    # Isolate production review policy from the independently tested 3000-item
    # selection rule, while keeping the real results, bindings and review rows.
    import llm_change_tool.core.exporting as exporting
    import llm_change_tool.core.jobs as jobs

    with transaction(project) as con:
        plan, members = jobs.validate_plan(con, one(con, "SELECT plan_id FROM llm_runs")["plan_id"])
        execute(con, "UPDATE work_plans SET mode='production'")
        execute(con, "UPDATE comparisons SET required=0,decision='AUTO_KEEP'")
    monkeypatch.setattr(jobs, "validate_plan", lambda *a: (dict(plan, mode="production"), members))
    monkeypatch.setattr(exporting, "validate_plan", jobs.validate_plan)
    assert len(review_queue(project, run, "required")) == 6
    assert review_summary(project, run)["required_remaining"] == 6
    from llm_change_tool.core.metrics import dashboard
    from llm_change_tool.core.quality import preparation_preview
    from llm_change_tool.core.reviews import select_auto_audit

    assert dashboard(project, run)["review_required"] == 6
    assert not preparation_preview(project, run)[0]["ready"]
    with pytest.raises(ValueError):
        select_auto_audit(project, run)
    report = final_gate(project, run)
    assert not report["passed"] and report["counts"]["review_required"] == 6
    assert compare_run(project, run)["required"] == 6
    for s in review_queue(project, run):
        save_review(project, run, s["id"], json.loads(s["original_labels"]), "Confirmed", "tester")
    assert review_summary(project, run)["required_remaining"] == 0
    assert final_gate(project, run)["passed"]


def test_other_cleanup_full_mock_save_reopen_export_restore(imported, tmp_path):
    _, root = imported
    # Change synthetic fixtures before importing into a fresh project.
    for path in root.rglob("*.json"):
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["Artifact"] = doc["artifact_detail"]["arti_other"] = "o"
        doc["artifact_detail"]["arti_other_detail"] = "synthetic old description"
        path.write_text(json.dumps(doc), encoding="utf-8")
    hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}
    project = create_project(tmp_path / "fresh", "Offline end-to-end")
    assert import_dataset(project, root)["samples"] == 6
    job = create_job(project, create_plan(project), RunConfig())
    run = run_job(project, job, provider=Matching())["run_id"]
    compare_run(project, run)
    for s in review_queue(project, run):
        save_review(project, run, s["id"], dict.fromkeys(KEYS, 0), "No other change", "tester")
    project = open_project(project.root)
    backup = backup_project(project)
    restored = restore_project(backup, tmp_path / "restored")
    for current in (project, restored):
        assert review_summary(current, run)["completed"] == 6
        assert final_gate(current, run)["all_human_reviewed"]
        output = Path(export_run(current, run)["path"])
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["mode"] == "pilot" and not manifest["production"]
        for s in review_queue(current, run):
            doc = json.loads((output / json.loads(s["paths"])["json"]).read_text(encoding="utf-8"))
            assert doc["artifact_detail"]["arti_other"] == "x"
            assert doc["artifact_detail"]["arti_other_detail"] == ""
            assert "unknown_metadata" in doc
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == h for p, h in hashes.items())
