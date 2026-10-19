import json

import pytest
from test_reviews import prepared

from llm_change_tool.core.exporting import export_run, final_gate
from llm_change_tool.core.reviews import compare_run, review_queue, save_review
from llm_change_tool.storage.store import execute, transaction


def approve(project, run):
    compare_run(project, run)
    for s in review_queue(project, run):
        save_review(
            project,
            run,
            s["id"],
            json.loads(s["original_labels"]),
            "확정",
            "tester",
            expected_revision=s["revision"],
        )


def test_e2e_export_and_stale_gate(imported):
    project, root = imported
    run = prepared(project)
    assert not final_gate(project, run)["passed"]
    compare_run(project, run)
    with pytest.raises(ValueError, match="Gate blocked"):
        export_run(project, run)
    approve(project, run)
    assert final_gate(project, run)["passed"]
    result = export_run(project, run)
    from pathlib import Path

    output = Path(result["path"])
    assert len(list(output.rglob("*.jpg"))) == 6
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["production"] is False
    for p in root.rglob("*.json"):
        exported = json.loads((output / p.relative_to(root)).read_text(encoding="utf-8"))
        assert (
            exported["unknown_metadata"]
            == json.loads(p.read_text(encoding="utf-8"))["unknown_metadata"]
        )
    s = review_queue(project, run)[0]
    save_review(
        project,
        run,
        s["id"],
        json.loads(s["original_labels"]),
        "보류",
        "tester",
        "DEFERRED",
        s["revision"],
    )
    assert not final_gate(project, run)["passed"]


def test_missing_compare_and_modified_source_block(imported):
    project, root = imported
    run = prepared(project)
    approve(project, run)
    with transaction(project) as con:
        execute(con, "DELETE FROM comparisons WHERE sample_id=(SELECT id FROM samples LIMIT 1)")
    assert not final_gate(project, run)["passed"]
    compare_run(project, run)
    p = next(root.rglob("*.jpg"))
    p.write_bytes(p.read_bytes() + b"changed")
    assert not final_gate(project, run)["passed"]


def test_export_failure_leaves_no_final_folder(imported, tmp_path, monkeypatch):
    import llm_change_tool.core.exporting as exporting

    project, _ = imported
    run = prepared(project)
    approve(project, run)

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(exporting.shutil, "copyfile", fail)
    target = tmp_path / "final-output"
    with pytest.raises(OSError, match="disk full"):
        export_run(project, run, target)
    assert not target.exists()
    assert not list(tmp_path.glob(".incomplete-*"))
