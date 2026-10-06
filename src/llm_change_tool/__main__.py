import argparse
import sys
from pathlib import Path

from llm_change_tool.ui.feedback import explain_error


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "--worker":
        from llm_change_tool.worker import main as worker_main

        return worker_main(arguments[1:])
    parser = argparse.ArgumentParser(description="LLM Change Tool v2")
    parser.add_argument("--project", type=Path, help="기존 프로젝트 폴더")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--gui-smoke", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(arguments)
    if args.self_test or args.gui_smoke:
        import json

        from llm_change_tool.core.demo import self_test

        try:
            if args.gui_smoke:
                from llm_change_tool.ui.smoke import gui_smoke

                result = gui_smoke()
            else:
                result = self_test()
            code = 0
        except Exception as exc:
            result = {"passed": False, "error": explain_error(str(exc))}
            code = 1
        if args.report:
            args.report.write_text(json.dumps(result), encoding="utf-8")
        if sys.stdout is not None:
            print(json.dumps(result))
        return code
    from PySide6.QtWidgets import QApplication, QMessageBox

    from llm_change_tool.core.projects import open_project
    from llm_change_tool.ui.window import MainWindow

    app = QApplication(sys.argv[:1])
    app.setApplicationName("LLM Change Tool v2")
    app.setOrganizationName("LLM Change Tool")
    window = MainWindow()
    if args.project:
        try:
            window.set_project(open_project(args.project))
        except Exception as exc:
            QMessageBox.warning(window, "프로젝트를 열 수 없습니다", explain_error(str(exc)))
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
