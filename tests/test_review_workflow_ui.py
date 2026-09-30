import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from test_desktop_flow import until
from test_ui_ux import ready

from llm_change_tool.core.reviews import review_queue, review_summary
from llm_change_tool.ui.components import ResultPanel
from llm_change_tool.ui.window import MainWindow


def test_required_queue_advances_without_skipping_and_summary_is_global(imported):
    app = QApplication.instance() or QApplication([])
    project, _, run = ready(imported)
    window = MainWindow()
    window.set_project(project)
    view = window.review_widget
    until(lambda: view.task and not view.task.isRunning())
    app.processEvents()
    view.filter.setCurrentIndex(view.filter.findData("required"))
    until(lambda: not view.task.isRunning())
    app.processEvents()
    ids = [s["id"] for s in view.items]
    view.reviewer.setText("tester")
    for i, sid in enumerate(ids):
        assert view.items[view.index]["id"] == sid
        assert view.save("DONE", True)
        until(lambda: not view.task.isRunning())
        app.processEvents()
        counts = review_summary(project, run)
        assert counts["total"] == 6
        assert counts["completed"] == i + 1
        assert counts["required_remaining"] == 5 - i
    assert not view.items
    assert not view.ai_button.isEnabled() and not view.buttons[-1].isEnabled()
    assert "전체 6" in view.summary.text() and "완료 6" in view.summary.text()
    window.close()
    app.processEvents()


def test_label_choice_is_only_a_draft_and_reason_is_visible(imported):
    app = QApplication.instance() or QApplication([])
    project, _, run = ready(imported)
    window = MainWindow()
    window.show()
    window.set_project(project)
    view = window.review_widget
    until(lambda: view.task and not view.task.isRunning())
    app.processEvents()
    window.navigate(2)
    app.processEvents()
    assert view.ai_reason.isVisible()
    assert not view.notes.toggle.isChecked()
    view.reviewer.setText("tester")
    view.apply_labels("ai")
    prediction = json.loads(view.items[0]["prediction"])
    assert view.reason.toPlainText() == prediction["reason"]
    assert review_queue(project, run)[0]["review_state"] is None
    view.autosave()
    assert review_queue(project, run)[0]["review_state"] == "DRAFT"
    view.apply_labels("original")
    assert review_queue(project, run)[0]["review_state"] == "DRAFT"
    assert view.save()
    assert review_queue(project, run)[0]["review_state"] == "DONE"
    window.close()
    app.processEvents()


def test_budget_and_auth_failures_have_actionable_feedback():
    app = QApplication.instance() or QApplication([])
    panel = ResultPanel()
    panel.set_result(
        {
            "state": "PAUSED",
            "counts": {"PENDING": 5},
            "cost_limit": 5,
            "message": "Estimated cost limit reached",
        }
    )
    assert "선택 작업 예산 변경" in panel.summary.text()
    panel.set_result(
        {
            "state": "FAILED",
            "counts": {"FAILED": 1},
            "failures": [{"error": "http_401", "count": 1}],
        }
    )
    assert any("API Key" in panel.values.item(i, 1).text() for i in range(panel.values.rowCount()))
    panel.close()
    app.processEvents()
