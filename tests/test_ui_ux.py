import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication
from test_desktop_flow import until

from llm_change_tool.core.jobs import RunConfig, create_job, run_job
from llm_change_tool.core.plans import create_plan
from llm_change_tool.core.projects import create_project
from llm_change_tool.core.reviews import compare_run
from llm_change_tool.ui.components import ResultPanel
from llm_change_tool.ui.window import MainWindow


def ready(imported):
    project, _ = imported
    job = create_job(project, create_plan(project), RunConfig())
    info = run_job(project, job)
    compare_run(project, info["run_id"])
    return project, job, info["run_id"]


def test_reopen_selects_existing_job_and_clears_other_project_results(imported, tmp_path):
    app = QApplication.instance() or QApplication([])
    project, job, run = ready(imported)
    window = MainWindow()
    window.show()
    assert not window.start_button.isEnabled()
    window.set_project(project)
    until(lambda: window.review_widget.task and not window.review_widget.task.isRunning())
    assert window.job_id == job and window.run_id == run
    assert len(window.review_widget.items) == 6
    assert not window.start_button.isEnabled()  # Completed jobs need no rerun.
    assert window.job_progress_percent.text() == "100%"
    assert window.job_progress.value() == window.job_progress.maximum() == 6
    assert "6" in window.dataset_hint.text()
    window.results.set_result({"passed": True, "counts": {}, "problems": []})
    window.set_project(create_project(tmp_path / "other", "새 작업"))
    assert window.job_id is None
    assert "통과" not in window.results.summary.text()
    assert not window.review_widget.reason.isEnabled()
    window.close()
    app.processEvents()


def test_navigation_small_window_image_fit_and_notes_do_not_overlap(imported):
    app = QApplication.instance() or QApplication([])
    project, _, _ = ready(imported)
    window = MainWindow()
    window.resize(1366, 768)
    window.show()
    window.set_project(project)
    until(lambda: window.review_widget.task and not window.review_widget.task.isRunning())
    window.navigate(2)
    app.processEvents()
    view = window.review_widget
    until(lambda: view.left.transform().m11() > 1)
    assert window.nav_buttons[2].isChecked()
    assert sum(button.isChecked() for button in window.nav_buttons) == 1
    assert view.left.viewport().width() > 180
    view.notes.toggle.setChecked(True)
    app.processEvents()
    bottom = view.labels.mapToGlobal(QPoint(0, view.labels.height())).y()
    top = view.reason.mapToGlobal(QPoint(0, 0)).y()
    assert bottom <= top
    assert window.size().width() == 1366 and window.size().height() == 768
    window.close()
    app.processEvents()


def test_errors_visible_on_origin_page_and_settings_are_discoverable(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    window.set_project(create_project(tmp_path / "project", "오류 표시"))
    window.navigate(1)
    window.provider.setCurrentIndex(window.provider.findData("openai"))
    assert window.api_settings.isVisible()
    window.provider.setCurrentIndex(window.provider.findData("mock"))
    assert not window.api_settings.isVisible()
    window.navigate(3)

    def fail(progress):
        raise ValueError("필수 검수 2건이 남아 있습니다.")

    window.background(fail)
    until(lambda: not window.active_task.isRunning())
    app.processEvents()
    assert "필수 검수 2건" in window.results.summary.text()
    assert window.results.summary.property("tone") == "error"
    window.close()
    app.processEvents()


def test_plain_text_feedback_and_export_folder_action(tmp_path):
    app = QApplication.instance() or QApplication([])
    panel = ResultPanel()
    path = tmp_path / "results"
    path.mkdir()
    panel.set_result({"path": str(path), "samples": 6})
    assert panel.output_path == str(path)
    assert not panel.open_folder.isHidden()
    panel.set_result({"error": "<b>sample name</b> cannot be read"})
    assert "<b>sample name</b>" in panel.summary.text()
    assert panel.open_folder.isHidden()
    panel.close()
    app.processEvents()


def test_result_panel_shows_percentage_and_counts_for_job_progress():
    app = QApplication.instance() or QApplication([])
    panel = ResultPanel()
    panel.set_result(
        {
            "state": "RUNNING",
            "counts": {"COMPLETED": 1, "FAILED": 1, "PENDING": 998},
            "usage": {},
        }
    )
    assert "0.20%" in panel.summary.text()
    assert "성공 1건" in panel.progress_detail.text()
    assert "실패 1건" in panel.progress_detail.text()
    assert panel.progress.value() == 2
    assert panel.progress.maximum() == 1000
    panel.close()
    app.processEvents()


def test_existing_openai_job_reveals_credentials_without_api_call(imported):
    app = QApplication.instance() or QApplication([])
    project, _ = imported
    config = RunConfig(provider="openai", model="test-model", input_price=1, output_price=2)
    job = create_job(project, create_plan(project), config)
    window = MainWindow()
    window.show()
    window.set_project(project)
    window.navigate(1)
    app.processEvents()
    assert window.job_id == job
    assert window.provider.currentData() == "openai"
    assert window.api_settings.isVisible()
    assert window.model.currentData() == "test-model"
    assert "test-model" in window.selected_run_hint.text()
    assert window.start_button.isEnabled()
    window.close()
    app.processEvents()


def test_model_and_pilot_count_are_choices_with_automatic_prices(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.set_project(create_project(tmp_path / "project", "선택 설정"))
    assert window.pilot_count.currentText() == "50"
    assert window.model.findData("gpt-4o-mini") >= 0
    assert window.model.findData("gpt-6-luna") >= 0
    assert window.model.findData("gpt-6.1-sol") >= 0
    window.provider.setCurrentIndex(window.provider.findData("openai"))
    window.model.setCurrentIndex(window.model.findData("gpt-6-luna"))
    assert "입력 $0.1" in window.model_price_hint.text()
    assert "출력 $0.5" in window.model_price_hint.text()
    window.close()
    app.processEvents()
