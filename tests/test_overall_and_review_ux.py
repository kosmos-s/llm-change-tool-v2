import json
import os
import sqlite3
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402
from test_desktop_flow import until  # noqa: E402
from test_reviews import prepared  # noqa: E402
from test_ui_ux import ready  # noqa: E402

from llm_change_tool.core.labels import KEYS, prompt_text  # noqa: E402
from llm_change_tool.core.metrics import label_metrics  # noqa: E402
from llm_change_tool.core.reviews import (  # noqa: E402
    compare_run,
    review_history,
    review_queue,
    review_summary,
    save_review,
)
from llm_change_tool.storage.store import execute, transaction  # noqa: E402
from llm_change_tool.ui.components import DashboardPanel  # noqa: E402
from llm_change_tool.ui.feedback import explain_error  # noqa: E402
from llm_change_tool.ui.window import MainWindow  # noqa: E402


def labels(**positive):
    return dict(dict.fromkeys(KEYS, 0), **positive)


def test_overall_micro_uses_independent_labels_and_reports_missing_predictions():
    truth = {"a": labels(arti=1, arti_bu=1, tree=1), "b": labels(farm=1), "c": labels()}
    predictions = {"a": labels(arti=1, arti_other=1, water=1), "b": labels(farm=1)}
    report = label_metrics(truth, predictions)
    scores = report["overall"]
    assert scores["labels"] == ["arti", "tree", "fore", "farm", "water"]
    assert (scores["tp"], scores["fp"], scores["fn"]) == (2, 1, 1)
    assert scores["f1"] == pytest.approx(2 / 3)
    assert report["coverage"] == pytest.approx(2 / 3)
    assert report["reference"] == 3 and report["matched"] == 2
    assert label_metrics({}, {})["overall"] is None
    assert not label_metrics({"a": labels()}, {"a": labels()})["overall"]["defined"]


def test_dashboard_explains_overall_coverage_and_undefined_f1():
    app = QApplication.instance() or QApplication([])
    panel = DashboardPanel()
    report = label_metrics({"a": labels(arti=1), "b": labels()}, {"a": labels(arti=1)})
    panel.set_result([dict(name="모델", **report)])
    assert "100.0%" in panel.overall.text() and "예측 누락" in panel.overall.text()
    assert "대표 변화 유무" in panel.metric_table.item(0, 0).text()
    assert "micro" in panel.metric_table.item(1, 0).text()
    panel.set_result([dict(name="모델", **label_metrics({"a": labels()}, {"a": labels()}))])
    assert "정의할 수 없음" in panel.overall.text()
    panel.close()
    app.processEvents()


def test_reader_does_not_wait_for_writer_and_cannot_write(imported):
    project, _ = imported
    run = prepared(project)
    compare_run(project, run)
    with transaction(project):
        started = time.monotonic()
        assert review_summary(project, run)["total"] == 6
        assert time.monotonic() - started < 1
        with transaction(project, readonly=True) as reader:
            with pytest.raises(OperationalError, match="readonly"):
                execute(reader, "UPDATE project SET name='must not write'")


def test_identical_save_is_idempotent_but_changes_and_stale_writes_are_not(imported):
    project, _ = imported
    run = prepared(project)
    compare_run(project, run)
    sample = review_queue(project, run)[0]
    values = json.loads(sample["original_labels"])
    revision = save_review(project, run, sample["id"], values, "확인", "검수자")
    assert (
        save_review(
            project, run, sample["id"], values, "확인", "검수자", expected_revision=revision
        )
        == revision
    )
    assert len(review_history(project, run, sample["id"])) == 1
    with pytest.raises(ValueError, match="changed"):
        save_review(project, run, sample["id"], values, "확인", "검수자")
    updated = save_review(
        project, run, sample["id"], values, "다시 확인", "검수자", expected_revision=revision
    )
    assert updated > revision
    assert len(review_history(project, run, sample["id"])) == 2


def test_async_save_keeps_event_loop_alive_and_advances_after_commit(imported):
    app = QApplication.instance() or QApplication([])
    project, _, run = ready(imported)
    window = MainWindow()
    window.set_project(project)
    view = window.review_widget
    until(lambda: view.task and not view.task.isRunning())
    app.processEvents()
    view.filter.setCurrentIndex(view.filter.findData("all"))
    view.reviewer.setText("검수자")
    first = view.items[view.index]["id"]
    writer = sqlite3.connect(project.database)
    writer.execute("BEGIN IMMEDIATE")
    ticked = []
    try:
        assert view.save("DONE", True, asynchronous=True)
        assert view.pending_save and not view.save(asynchronous=True)
        QTimer.singleShot(20, lambda: ticked.append(True))
        until(lambda: bool(ticked))
        assert view.items[view.index]["id"] == first
        assert not review_history(project, run, first)
    finally:
        writer.rollback()
        writer.close()
    until(lambda: not view.pending_save and view.task and not view.task.isRunning())
    app.processEvents()
    assert view.items[view.index]["id"] != first
    assert review_summary(project, run)["completed"] == 1
    window.close()
    app.processEvents()


def test_errors_are_korean_and_do_not_show_unknown_private_text():
    assert "검수자 이름" in explain_error("Reviewer name is required (max 120 chars)")
    assert "원본 파일" in explain_error("Source integrity errors: 3")
    assert "잠시 후" in explain_error("database is locked")
    message = explain_error("unexpected private provider text")
    assert "오류 식별번호" in message and "private provider" not in message


def test_default_prompt_contract_and_guideline_exceptions():
    prompt = prompt_text()
    assert "reason_ko" not in prompt and "class 값" not in prompt and "change=" not in prompt
    assert all(key in prompt for key in KEYS)
    assert "T1(과거), T2(현재)" in prompt
    assert "명시적 예외" in prompt and "축척 정보가 없으면" in prompt
    assert "계절" in prompt and "인위적 전환" in prompt
    assert "기존 JSON 라벨은 입력되지 않는다" in prompt


def test_position_and_opt_in_name_restore_by_sample_id(imported, tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    settings_path = str(tmp_path / "settings.ini")
    monkeypatch.setattr(
        "llm_change_tool.ui.reviewer.QSettings",
        lambda *args: QSettings(settings_path, QSettings.Format.IniFormat),
    )
    project, _, _ = ready(imported)
    window = MainWindow()
    window.set_project(project)
    view = window.review_widget
    until(lambda: view.task and not view.task.isRunning())
    app.processEvents()
    view.reviewer.setText("검수자")
    assert view.settings.value("reviewer_name", "") == ""
    view.remember_name.setChecked(True)
    view.move(1)
    until(lambda: not view.task.isRunning())
    app.processEvents()
    sample_id = view.items[view.index]["id"]
    window.close()
    app.processEvents()
    reopened = MainWindow()
    reopened.set_project(project)
    until(lambda: reopened.review_widget.task and not reopened.review_widget.task.isRunning())
    app.processEvents()
    assert reopened.review_widget.reviewer.text() == "검수자"
    assert reopened.review_widget.items[reopened.review_widget.index]["id"] == sample_id
    reopened.review_widget.remember_name.setChecked(False)
    assert reopened.review_widget.settings.value("reviewer_name", "") == ""
    reopened.close()
    app.processEvents()
