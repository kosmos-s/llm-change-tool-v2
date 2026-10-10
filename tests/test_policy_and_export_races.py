import json
import shutil

import pytest
from PIL import Image
from test_gate import approve
from test_reviews import prepared

from llm_change_tool.core.datasets import import_dataset, source_identities
from llm_change_tool.core.exporting import export_run
from llm_change_tool.core.jobs import RunConfig, create_job, run_job
from llm_change_tool.core.metrics import create_golden
from llm_change_tool.core.plans import create_plan
from llm_change_tool.core.projects import create_project
from llm_change_tool.core.reviews import review_queue, save_review
from llm_change_tool.storage.store import one, transaction


def test_candidate_golden_allows_excluded_unpaired_image(imported, tmp_path):
    _, root = imported
    Image.new("RGB", (32, 32), "orange").save(root / "unpaired.jpg")
    project = create_project(tmp_path / "candidate-project", "후보 정책")
    report = import_dataset(project, root)
    assert any(issue["error"] == "orphan_image" for issue in report["errors"])
    job = create_job(project, create_plan(project, "pilot", candidate_policy=True), RunConfig())
    run_job(project, job)
    with transaction(project, readonly=True) as con:
        run = one(con, "SELECT run_id FROM jobs WHERE id=:id", id=job)["run_id"]
    approve(project, run)
    golden = create_golden(project, run, "검증", purpose="evaluation", split="test")
    assert golden["samples"] > 0


def test_rgb_identity_ignores_jpeg_metadata_bytes(imported, tmp_path):
    _, root = imported
    first = next(root.rglob("*.jpg"))
    other = root / "dataset" / "val" / "metadata_combined.jpg"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_bytes(first.read_bytes() + b"metadata-only-tail")
    source_json = first.with_suffix(".json")
    other.with_suffix(".json").write_bytes(source_json.read_bytes())
    project = create_project(tmp_path / "rgb-project", "영상 내용")
    import_dataset(project, root)
    identities = source_identities(project)
    assert len(set(identities.values())) == len(identities) - 1


def test_export_rejects_concurrent_review_change_without_publishing(
    imported, tmp_path, monkeypatch
):
    project, _ = imported
    run = prepared(project)
    approve(project, run)
    sample = review_queue(project, run)[0]
    original_copy = shutil.copyfile
    changed = []

    def copying(source, target, *args, **kwargs):
        if not changed:
            save_review(
                project,
                run,
                sample["id"],
                json.loads(sample["reviewed_labels"]),
                "내보내기 중 재검수",
                "다른 검수자",
                expected_revision=sample["revision"],
            )
            changed.append(True)
        return original_copy(source, target, *args, **kwargs)

    monkeypatch.setattr("llm_change_tool.core.exporting.shutil.copyfile", copying)
    destination = tmp_path / "must-not-publish"
    with pytest.raises(ValueError, match="검수 내용이 변경"):
        export_run(project, run, destination)
    assert changed and not destination.exists()
    assert not list(tmp_path.glob(".incomplete-*"))
