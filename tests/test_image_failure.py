import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from test_desktop_flow import until
from test_ui_ux import ready

from llm_change_tool.core.reviews import review_queue
from llm_change_tool.ui.window import MainWindow


def test_failed_image_clears_previous_frame_and_blocks_save(imported):
    app = QApplication.instance() or QApplication([])
    project, _, run = ready(imported)
    root = imported[1]
    window = MainWindow()
    window.set_project(project)
    view = window.review_widget
    until(lambda: view.task and not view.task.isRunning())
    app.processEvents()
    assert view.loaded_sample_id == view.items[0]["id"]
    next_sample = view.items[1]
    path = root / json.loads(next_sample["paths"])["combined"]
    raw = path.read_bytes()
    path.unlink()
    view.move(1)
    assert view.images is None and not view.left.scene().items()
    assert not view.save()
    until(lambda: not view.task.isRunning())
    app.processEvents()
    assert view.images is None and not view.right.scene().items()
    view.reviewer.setText("tester")
    assert not view.save() and not view.save("DRAFT")
    assert not view.buttons[-1].isEnabled()
    assert review_queue(project, run)[1]["review_state"] is None
    path.write_bytes(raw)
    view.reload()
    until(lambda: not view.task.isRunning())
    app.processEvents()
    assert view.loaded_sample_id == next_sample["id"]
    assert view.save()
    window.close()
    app.processEvents()


def test_editing_korean_reason_invalidates_previous_english(imported):
    app = QApplication.instance() or QApplication([])
    project, _, _ = ready(imported)
    window = MainWindow()
    window.set_project(project)
    view = window.review_widget
    until(lambda: view.task and not view.task.isRunning())
    app.processEvents()
    view.reason_en.setText("Old explanation")
    view.reason.setPlainText("새 판정 근거")
    assert view.reason_en.text() == ""
    view.reason_en.setText("New explanation")
    assert view.reason_en.text() == "New explanation"
    view.reviewer.setText("tester")
    assert view.save()
    window.close()
    app.processEvents()
