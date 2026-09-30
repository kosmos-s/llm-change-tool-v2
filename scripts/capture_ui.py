"""Capture the real desktop with generated synthetic data only (no API calls)."""

import argparse
import json
import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image, ImageDraw
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from llm_change_tool.core.datasets import import_dataset
from llm_change_tool.core.demo import generate_dataset
from llm_change_tool.core.exporting import final_gate
from llm_change_tool.core.jobs import RunConfig, create_job, run_job
from llm_change_tool.core.labels import FIELDS
from llm_change_tool.core.metrics import dashboard
from llm_change_tool.core.plans import create_plan
from llm_change_tool.core.projects import create_project
from llm_change_tool.core.reviews import compare_run, review_queue, save_review
from llm_change_tool.ui.window import MainWindow


def synthetic_preview(root):
    generate_dataset(root)
    for path in root.rglob("*.json"):
        doc = json.loads(path.read_text(encoding="utf-8"))
        for field in FIELDS:
            if field["key"] in ("arti", "arti_bu", "tree"):
                parent = doc
                for part in field["path"][:-1]:
                    parent = parent[part]
                parent[field["path"][-1]] = "o"
        path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    for index, path in enumerate(sorted(root.rglob("*.jpg"))):
        pair = Image.new("RGB", (1024, 512))
        draw = ImageDraw.Draw(pair)
        for time in range(2):
            dx = 512 * time
            draw.rectangle((dx, 0, dx + 511, 511), fill=(121 + index * 2, 148, 113))
            for x in range(0, 512, 64):
                for y in range(0, 512, 64):
                    draw.rectangle(
                        (dx + x + 3, y + 3, dx + x + 59, y + 59),
                        fill=(133 + (x // 64) % 3 * 12, 151 + (y // 64) % 3 * 9, 98),
                    )
            draw.polygon(
                [(dx, 330), (dx + 512, 430), (dx + 512, 455), (dx, 355)], fill=(213, 208, 192)
            )
            draw.rectangle((dx + 250, 0, dx + 275, 512), fill=(213, 208, 192))
            buildings = [(66, 40), (342, 65), (350, 170), (80, 245)] + (
                [(102, 125)] if time else []
            )
            for x, y in buildings:
                draw.rectangle((dx + x + 4, y + 5, dx + x + 67, y + 44), fill=(86, 97, 86))
                draw.rectangle((dx + x, y, dx + x + 60, y + 35), fill=(189, 194, 191))
                draw.line((dx + x, y + 17, dx + x + 60, y + 17), fill=(229, 229, 223), width=3)
            for x, y in [(27, 155), (182, 36), (418, 295), (40, 429)]:
                draw.ellipse((dx + x, y, dx + x + 34, y + 34), fill=(59, 109, 72))
        pair.save(path)


def settle(app, condition=lambda: True):
    loop, timer, deadline = QEventLoop(), QTimer(), QTimer()
    timer.timeout.connect(lambda: loop.quit() if condition() else None)
    timer.start(40)
    deadline.setSingleShot(True)
    deadline.timeout.connect(loop.quit)
    deadline.start(15000)
    loop.exec()
    timer.stop()
    deadline.stop()
    app.processEvents()
    if not condition():
        raise RuntimeError("UI capture timed out")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("artifacts/ui"))
    parser.add_argument(
        "--font-dir", type=Path, help="Optional local Korean fonts for Linux previews"
    )
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    if args.font_dir:
        for path in args.font_dir.glob("*.ttf"):
            QFontDatabase.addApplicationFont(str(path))
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="llm-ui-synthetic-") as temporary:
        root = Path(temporary)
        project = create_project(root / "project", "항공영상 검수 · 합성 데모")
        synthetic_preview(root / "data")
        import_dataset(project, root / "data")
        job = create_job(project, create_plan(project), RunConfig())
        run = run_job(project, job)["run_id"]
        compare_run(project, run)
        for sample in review_queue(project, run)[-2:]:
            save_review(
                project,
                run,
                sample["id"],
                json.loads(sample["original_labels"]),
                "합성 UI 예시의 검수 메모",
                "검수자 A",
            )
        window = MainWindow()
        window.show()
        window.resize(1480, 960)
        settle(app)
        window.grab().save(str(args.output / "home.png"))
        window.set_project(project)
        settle(app, lambda: window.review_widget.task and not window.review_widget.task.isRunning())
        window.review_widget.reviewer.setText("검수자 A")
        for index, name in [
            (1, "analysis"),
            (2, "review"),
            (3, "quality"),
            (4, "team"),
            (5, "dashboard"),
            (6, "data-quality"),
        ]:
            window.navigate(index)
            if index == 3:
                window.results.set_result(final_gate(project, run))
            if index == 5:
                window.analysis.set_result(dashboard(project, run))
            if index == 6:
                window.quality_page.refresh()
                settle(app, lambda: window.active_task and not window.active_task.isRunning())
            settle(app)
            window.grab().save(str(args.output / f"{name}.png"))
            if index == 1:
                window.provider.setCurrentIndex(window.provider.findData("openai"))
                window.model.setCurrentIndex(window.model.findData("gpt-6-luna"))
                settle(app)
                window.grab().save(str(args.output / "analysis-openai.png"))
                window.provider.setCurrentIndex(window.provider.findData("mock"))
        window.resize(1366, 768)
        window.navigate(6)
        settle(app)
        window.grab().save(str(args.output / "data-quality-1366.png"))
        window.navigate(2)
        settle(app)
        window.grab().save(str(args.output / "review-1366.png"))
        window.review_widget.notes.toggle.setChecked(True)
        settle(app)
        window.grab().save(str(args.output / "review-notes-1366.png"))
        window.close()
        app.processEvents()
    print(f"Synthetic UI previews: {args.output}")


if __name__ == "__main__":
    main()
