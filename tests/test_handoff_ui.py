import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from test_desktop_flow import until

from llm_change_tool.core.datasets import import_dataset
from llm_change_tool.core.jobs import RunConfig, create_job, run_job
from llm_change_tool.core.plans import create_plan
from llm_change_tool.core.projects import create_project
from llm_change_tool.core.reviews import compare_run
from llm_change_tool.ui.components import ResultPanel
from llm_change_tool.ui.window import MainWindow


def test_other_description_in_review_tracks_checkbox_and_reopen(imported, tmp_path):
    app = QApplication.instance() or QApplication([])
    _, root = imported
    for p in root.rglob("*.json"):
        doc = json.loads(p.read_text(encoding="utf-8"))
        doc["Artifact"] = doc["artifact_detail"]["arti_other"] = "o"
        doc["artifact_detail"]["arti_other_detail"] = "old synthetic detail"
        p.write_text(json.dumps(doc), encoding="utf-8")
    project = create_project(tmp_path / "other", "Synthetic UI")
    import_dataset(project, root)
    job = create_job(project, create_plan(project), RunConfig())
    run = run_job(project, job)["run_id"]
    compare_run(project, run)
    window = MainWindow()
    window.set_project(project)
    view = window.review_widget
    until(lambda: view.task and not view.task.isRunning())
    app.processEvents()
    view.auto.setChecked(False)
    assert "old synthetic detail" in view.other_detail.text()
    view.boxes["arti_other"].setChecked(False)
    assert "old synthetic detail" not in view.other_detail.text()
    view.reviewer.setText("tester")
    view.reason.setPlainText("Other change removed")
    assert view.save()
    view.reload()
    until(lambda: not view.task.isRunning())
    app.processEvents()
    assert not view.boxes["arti_other"].isChecked()
    assert "old synthetic detail" not in view.other_detail.text()
    window.close()
    app.processEvents()


def test_gate_panel_discloses_human_coverage_and_legacy_policy():
    app = QApplication.instance() or QApplication([])
    panel = ResultPanel()
    panel.set_result(
        dict(
            passed=True, problems=[], counts=dict(total=6, human_complete=0), legacy_core_pilot=True
        )
    )
    assert "0 / 6" in panel.summary.text()
    assert "Gate 통과는 전건 사람 검수" in panel.summary.text()
    assert "이전 core 시험용 정책" in panel.summary.text()
    panel.close()
    app.processEvents()
