import json

import pytest
from test_reviews import prepared

from llm_change_tool.core.exchange import export_reviews, import_reviews
from llm_change_tool.core.exporting import export_run, final_gate
from llm_change_tool.core.labels import KEYS, effective_doc
from llm_change_tool.core.projects import backup_project, restore_project
from llm_change_tool.core.reviews import (
    compare_run,
    review_history,
    review_queue,
    save_review,
    undo_review,
)


def test_changed_labels_do_not_keep_contradictory_english(imported):
    project, _ = imported
    run = prepared(project)
    compare_run(project, run)
    sample = review_queue(project, run)[0]
    source = json.loads(sample["original_raw"])
    source["reason"] = "There is no change."
    source["reason_en"] = source["reason"]
    source["reason_ko"] = "변화 없음"
    raw = json.dumps(source).encode()
    labels = dict.fromkeys(KEYS, 0)
    assert effective_doc(raw, labels, "")["reason"] == source["reason"]
    labels["arti"] = labels["arti_bu"] = 1
    with pytest.raises(ValueError, match="근거"):
        effective_doc(raw, labels, "")
    result = effective_doc(raw, labels, "건물 신축")
    assert result["reason"] == result["reason_en"] == ""
    assert result["reason_ko"] == "건물 신축"
    result = effective_doc(raw, labels, "건물 신축", "A building was constructed.")
    assert result["reason"] == result["reason_en"] == "A building was constructed."
    assert json.loads(raw) == source


def test_bilingual_review_survives_export_and_team_exchange(imported, tmp_path):
    project, _ = imported
    run = prepared(project)
    compare_run(project, run)
    other = restore_project(backup_project(project), tmp_path / "other")
    samples = review_queue(project, run)
    for s in samples:
        save_review(
            project,
            run,
            s["id"],
            json.loads(s["original_labels"]),
            "변화 없음",
            "tester",
            reason_en="No change.",
        )
    assert final_gate(project, run)["passed"]
    from pathlib import Path

    output = Path(export_run(project, run)["path"])
    for s in samples:
        data = json.loads((output / json.loads(s["paths"])["json"]).read_text(encoding="utf-8"))
        assert data["reason"] == "No change."
        assert data["reason_ko"] == "변화 없음"
    assert import_reviews(other, run, export_reviews(project, run)["path"])["NEW"] == 6
    assert all(s["reviewed_reason_en"] == "No change." for s in review_queue(other, run))
    # A translation-only change is also a team conflict, never silently ignored.
    s = review_queue(project, run)[0]
    save_review(
        project,
        run,
        s["id"],
        json.loads(s["original_labels"]),
        "변화 없음",
        "tester",
        expected_revision=s["revision"],
        reason_en="No meaningful change.",
    )
    assert import_reviews(other, run, export_reviews(project, run)["path"])["CONFLICT"] == 1


def test_undo_walks_back_to_original_and_can_branch(imported):
    project, _ = imported
    run = prepared(project)
    compare_run(project, run)
    s = review_queue(project, run)[0]
    labels = json.loads(s["original_labels"])
    revision = None
    for reason in ("A", "B", "C"):
        revision = save_review(
            project,
            run,
            s["id"],
            labels,
            reason,
            "tester",
            expected_revision=revision,
            reason_en=reason,
        )
    for reason in ("B", "A", "Undo to original"):
        undo_review(project, run, s["id"], "tester")
        s = review_queue(project, run)[0]
        assert s["reviewed_reason"] == reason
    with pytest.raises(ValueError, match="더 이전"):
        undo_review(project, run, s["id"], "tester")
    assert len(review_history(project, run, s["id"])) == 6
    revision = save_review(
        project, run, s["id"], labels, "D", "tester", expected_revision=s["revision"]
    )
    with pytest.raises(ValueError, match="changed"):
        undo_review(project, run, s["id"], "tester", expected_revision=s["revision"])
    undo_review(project, run, s["id"], "tester", expected_revision=revision)
    assert review_queue(project, run)[0]["review_state"] == "DRAFT"


def test_changed_labels_require_reason_but_draft_can_be_incomplete(imported):
    project, _ = imported
    run = prepared(project)
    compare_run(project, run)
    s = review_queue(project, run)[0]
    labels = json.loads(s["original_labels"])
    labels["arti"] = labels["arti_bu"] = 1
    with pytest.raises(ValueError, match="근거"):
        save_review(project, run, s["id"], labels, "", "tester")
    save_review(project, run, s["id"], labels, "", "tester", "DRAFT")
    assert not final_gate(project, run)["passed"]
