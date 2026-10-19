import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication
from test_desktop_flow import until
from test_ui_ux import ready

from llm_change_tool.core.labels import FIELDS, KEYS
from llm_change_tool.core.metrics import create_golden
from llm_change_tool.core.reviews import (
    BLIND_ORIGIN,
    review_history,
    review_queue,
    review_summary,
    save_review,
)
from llm_change_tool.storage.store import execute, transaction
from llm_change_tool.ui.feedback import explain_error
from llm_change_tool.ui.window import MainWindow


def seed_source_drafts(project, run):
    # Mirrors the prepared local projects: drafts copied from source labels.
    for sample in review_queue(project, run):
        save_review(
            project,
            run,
            sample["id"],
            json.loads(sample["original_labels"]),
            "Offline Mock preparation only; actual human review pending.",
            "offline workflow preparation",
            "DRAFT",
        )


def test_blind_done_requires_reason_and_keeps_provenance(imported):
    project, _, run = ready(imported)
    sample = review_queue(project, run)[0]
    labels = json.loads(sample["original_labels"])
    with pytest.raises(ValueError, match="Independent review requires a reason"):
        save_review(project, run, sample["id"], labels, " ", "tester", blind=True)
    first = save_review(project, run, sample["id"], labels, "", "tester")
    second = save_review(
        project, run, sample["id"], labels, "영상 확인", "tester", expected_revision=first
    )
    # The same content judged blind is a new, distinguishable decision.
    again = save_review(
        project,
        run,
        sample["id"],
        labels,
        "영상 확인",
        "tester",
        expected_revision=second,
        blind=True,
    )
    assert again != second
    assert (
        save_review(
            project,
            run,
            sample["id"],
            labels,
            "영상 확인",
            "tester",
            expected_revision=again,
            blind=True,
        )
        == again
    )
    assert "판정 근거" in explain_error("Independent review requires a reason")
    origins = [r["origin"] for r in review_history(project, run, sample["id"])]
    assert origins == ["local", "local", BLIND_ORIGIN]
    counts = review_summary(project, run)
    assert counts["completed"] == 1 and counts["blind_completed"] == 1


def test_golden_records_blind_share_without_changing_fingerprint(imported):
    project, _, run = ready(imported)
    samples = review_queue(project, run)
    for i, sample in enumerate(samples[:2]):
        save_review(
            project,
            run,
            sample["id"],
            json.loads(sample["original_labels"]),
            "영상 확인",
            "tester",
            blind=i == 0,
        )
    golden = create_golden(project, run, "mixed")
    assert golden["samples"] == 2
    assert golden["blind_reviews"] == 1 and not golden["all_blind"]
    blind_only = create_golden(project, run, "blind", {samples[0]["id"]})
    assert blind_only["all_blind"]


def test_blind_mode_hides_source_seeded_drafts_and_records_decision(imported):
    app = QApplication.instance() or QApplication([])
    project, _, run = ready(imported)
    seed_source_drafts(project, run)
    window = MainWindow()
    window.show()
    window.set_project(project)
    view = window.review_widget
    until(lambda: view.task and not view.task.isRunning())
    app.processEvents()
    view.reviewer.setText("tester")
    view.blind.setChecked(True)
    until(lambda: not view.task.isRunning())
    app.processEvents()
    sample_id = view.items[view.index]["id"]
    assert view.labels.item(0, 1).text() == "숨김" and view.labels.item(0, 2).text() == "숨김"
    assert not view.original_button.isEnabled() and not view.ai_button.isEnabled()
    assert not view.signals.isVisible()
    assert view.reason.toPlainText() == ""
    assert "Offline Mock" not in view.reason.toPlainText()
    editable = [f["key"] for f in FIELDS if "fixed" not in f]
    assert all(view.boxes[k].checkState() == Qt.CheckState.PartiallyChecked for k in editable)
    assert not view.save()
    assert "미확정" in view.decision_hint.text()
    for key in editable:
        view.boxes[key].setCheckState(Qt.CheckState.Unchecked)
    assert not view.boxes[editable[0]].isTristate()
    assert not view.save()
    assert "근거" in view.decision_hint.text()
    view.reason.setPlainText("T1/T2 비교 결과 변화 없음")
    assert view.save()
    latest = review_history(project, run, sample_id)[-1]
    assert latest["origin"] == BLIND_ORIGIN and latest["state"] == "DONE"
    assert json.loads(latest["labels"]) == dict.fromkeys(KEYS, 0)
    assert "독립 판정 완료 1" in view.summary.text()
    # One reviewer per PC: correcting the name never hides the saved decision.
    view.reviewer.setText("another tester")
    assert view.reason.toPlainText() == "T1/T2 비교 결과 변화 없음"
    view.reviewer.setText("tester")
    view.undo()
    assert review_history(project, run, sample_id)[-1]["revision"] == latest["revision"]
    # The reviewer's own blind decision is shown again after reopening.
    view.reload()
    until(lambda: not view.task.isRunning())
    app.processEvents()
    assert view.items[view.index]["id"] == sample_id
    assert view.reason.toPlainText() == "T1/T2 비교 결과 변화 없음"
    assert view.boxes[editable[0]].checkState() == Qt.CheckState.Unchecked
    view.blind.setChecked(False)
    until(lambda: not view.task.isRunning())
    app.processEvents()
    assert view.labels.item(0, 1).text() in ("변화", "없음")
    assert view.original_button.isEnabled()
    window.close()
    app.processEvents()


def test_blind_toggle_waits_for_unsaved_edits_and_is_remembered(imported):
    app = QApplication.instance() or QApplication([])
    project, _, run = ready(imported)
    window = MainWindow()
    window.show()
    window.set_project(project)
    view = window.review_widget
    until(lambda: view.task and not view.task.isRunning())
    app.processEvents()
    view.auto.setChecked(False)
    view.reason.setPlainText("수정 중")
    assert view.dirty
    view.blind.setChecked(True)
    assert not view.blind.isChecked()
    assert "저장한 뒤" in view.status.text()
    view.load_current()
    until(lambda: not view.task.isRunning())
    app.processEvents()
    view.blind.setChecked(True)
    until(lambda: not view.task.isRunning())
    assert view.blind.isChecked()
    assert view.bind(None, None)
    assert not view.blind.isChecked()
    window.set_project(project)
    until(lambda: view.project is project and not view.task.isRunning())
    assert view.blind.isChecked()
    assert review_queue(project, run)[0]["review_state"] is None
    window.close()
    app.processEvents()


@pytest.mark.parametrize("stale", [False, True])
def test_blind_reopens_current_decision_and_hides_stale_one(imported, monkeypatch, stale):
    app = QApplication.instance() or QApplication([])
    project, _, run = ready(imported)
    sample = review_queue(project, run)[0]
    save_review(
        project,
        run,
        sample["id"],
        dict.fromkeys(KEYS, 0),
        "이전 독립 근거",
        "first",
        blind=True,
    )
    if stale:
        with transaction(project) as con:
            execute(
                con,
                "UPDATE comparisons SET result_hash='changed' WHERE run_id=:run AND sample_id=:sid",
                run=run,
                sid=sample["id"],
            )
    window = MainWindow()
    window.show()
    try:
        window.set_project(project)
        view = window.review_widget
        until(lambda: view.task and not view.task.isRunning())
        # A different name still sees the decision: names are not access control.
        view.reviewer.setText("second")
        view.blind.setChecked(True)
        until(lambda: not view.task.isRunning())
        app.processEvents()
        editable = [f["key"] for f in FIELDS if "fixed" not in f]
        messages = []
        monkeypatch.setattr(
            "llm_change_tool.ui.reviewer.QMessageBox.information",
            lambda *args: messages.append(args[-1]),
        )
        view.history()
        if stale:
            # A decision on an earlier AI/original result is not reopened.
            assert view.reason.toPlainText() == ""
            assert all(
                view.boxes[k].checkState() == Qt.CheckState.PartiallyChecked for k in editable
            )
            assert "이전 독립 근거" not in messages[-1]
        else:
            assert view.reason.toPlainText() == "이전 독립 근거"
            assert view.boxes[editable[0]].checkState() == Qt.CheckState.Unchecked
            assert "이전 독립 근거" in messages[-1]
    finally:
        window.close()
        app.processEvents()


def test_blind_unnamed_reviewer_can_enter_name_after_judging(imported):
    app = QApplication.instance() or QApplication([])
    project, _, run = ready(imported)
    window = MainWindow()
    window.show()
    try:
        window.set_project(project)
        view = window.review_widget
        until(lambda: view.task and not view.task.isRunning())
        view.reviewer.clear()
        view.blind.setChecked(True)
        until(lambda: not view.task.isRunning())
        app.processEvents()
        view.auto.setChecked(False)
        for field in FIELDS:
            if "fixed" not in field:
                view.boxes[field["key"]].setCheckState(Qt.CheckState.Unchecked)
        view.reason.setPlainText("영상으로 먼저 판정한 근거")
        for name in ("t", "te", "tester"):
            view.reviewer.setText(name)
            assert view.reviewer.text() == name
            assert view.reason.toPlainText() == "영상으로 먼저 판정한 근거"
        assert view.save()
        sample = view.items[view.index]
        latest = review_history(project, run, sample["id"])[-1]
        assert latest["reviewer"] == "tester" and latest["origin"] == BLIND_ORIGIN
        assert not view.dirty
    finally:
        window.close()
        app.processEvents()


def test_ui_tests_use_isolated_settings(imported):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        # conftest swaps the registry-backed settings for a per-test INI file.
        assert window.review_widget.settings.format() == QSettings.Format.IniFormat
    finally:
        window.close()
        app.processEvents()
