import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from test_desktop_flow import until
from test_quality_workflow import prepared

from llm_change_tool.core.reviews import review_queue
from llm_change_tool.ui.window import MainWindow


def test_unknown_click_autosaves_and_deferred_survives_navigation(tmp_path):
    app = QApplication.instance() or QApplication([])
    project, _, run = prepared(tmp_path, "unknown")
    window = MainWindow()
    window.set_project(project)
    view = window.review_widget
    until(lambda: view.task and not view.task.isRunning())
    app.processEvents()
    index = next(
        i for i, s in enumerate(view.items) if json.loads(s["original_labels"])["arti_bu"] is None
    )
    sid = view.items[index]["id"]
    view.index = index
    view.load_current()
    until(lambda: not view.task.isRunning())
    app.processEvents()
    view.reviewer.setText("tester")
    assert view.boxes["arti_bu"].checkState() == Qt.CheckState.PartiallyChecked
    assert not view.save("DONE")
    assert view.save("DEFERRED")
    view.boxes["arti_bu"].click()
    assert view.dirty and view.timer.isActive()
    view.autosave()
    item = next(s for s in review_queue(project, run) if s["id"] == sid)
    assert json.loads(item["reviewed_labels"])["arti_bu"] == 1
    view.move(1)
    until(lambda: not view.task.isRunning())
    app.processEvents()
    view.index = index
    view.load_current()
    until(lambda: not view.task.isRunning())
    app.processEvents()
    assert view.boxes["arti_bu"].isChecked()
    window.close()
    app.processEvents()


def test_quality_page_refresh_and_open_sample(tmp_path):
    app = QApplication.instance() or QApplication([])
    project, _, _ = prepared(tmp_path, "duplicate")
    window = MainWindow()
    window.set_project(project)
    until(lambda: window.review_widget.task and not window.review_widget.task.isRunning())
    app.processEvents()
    window.navigate(6)
    window.quality_page.refresh()
    until(lambda: window.active_task and not window.active_task.isRunning())
    app.processEvents()
    page = window.quality_page
    assert page.duplicates.rowCount() == 2
    assert page.issues.rowCount() >= 1
    page.open_review(page.duplicates, 0)
    until(lambda: not window.review_widget.task.isRunning())
    app.processEvents()
    assert window.tabs.currentIndex() == 2
    window.close()
    app.processEvents()
