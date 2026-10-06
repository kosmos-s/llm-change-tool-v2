import json
import shutil
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QProcess, Qt, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from llm_change_tool.core.projects import Project, backup_project, create_project, open_project
from llm_change_tool.ui.components import card, role
from llm_change_tool.ui.components import text_label as label
from llm_change_tool.ui.feedback import explain_error
from llm_change_tool.ui.theme import apply_theme


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        apply_theme()
        self.project: Project | None = None
        self.process: QProcess | None = None
        self.report_dir = None
        self.worker_timed_out = False
        self.worker_timer = QTimer(self)
        self.worker_timer.setSingleShot(True)
        self.worker_timer.timeout.connect(self._worker_timeout)
        self.setMinimumSize(1100, 740)
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        self.project_intro = label(
            "원본은 그대로, 검수 결과는 안전하게. 프로젝트를 선택하고 작업을 시작하세요.", "muted"
        )
        layout.addWidget(self.project_intro)
        actions = QHBoxLayout()
        for title, hint, button_title, method, name in [
            (
                "새 작업 시작",
                "작업 상태와 검수 이력을 저장할 로컬 프로젝트를 만듭니다.",
                "＋  새 프로젝트",
                self._new_project,
                "new_button",
            ),
            (
                "이전 작업 이어가기",
                "저장해 둔 프로젝트를 열어 마지막 작업을 이어갑니다.",
                "프로젝트 열기",
                self._open_project,
                "open_button",
            ),
        ]:
            frame, content = card(title, hint)
            button = QPushButton(button_title)
            button.clicked.connect(method)
            if name == "new_button":
                role(button, "primary")
            setattr(self, name, button)
            content.addWidget(button)
            actions.addWidget(frame)
        layout.addLayout(actions)
        frame, details = card("현재 프로젝트")
        self.project_name = label("아직 프로젝트를 선택하지 않았습니다.", "sectionTitle")
        self.project_details = label("위에서 새로 만들거나 기존 프로젝트를 열어 주세요.", "muted")
        self.project_details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        details.addWidget(self.project_name)
        details.addWidget(self.project_details)
        row = QHBoxLayout()
        self.diagnose_button = QPushButton("프로젝트 점검")
        self.diagnose_button.clicked.connect(self.start_diagnosis)
        self.backup_button = QPushButton("안전하게 백업")
        self.backup_button.clicked.connect(self._backup)
        row.addWidget(self.diagnose_button)
        row.addWidget(self.backup_button)
        row.addStretch()
        details.addLayout(row)
        self.result = label(
            "백업에는 작업 DB가 저장됩니다. 원본 데이터는 별도로 보관하세요.", "muted"
        )
        details.addWidget(self.result)
        layout.addWidget(frame)
        frame, content = card(
            "이 순서로 진행하세요", "왼쪽 메뉴에서 언제든 원하는 단계로 이동할 수 있습니다."
        )
        row = QHBoxLayout()
        for number, title, hint, index in [
            ("01", "데이터 · AI 분석", "폴더 가져오기와 자동 판정", 1),
            ("02", "이미지 검수", "두 시점을 보고 라벨 확정", 2),
            ("03", "품질 · 내보내기", "누락 확인 후 최종 결과 저장", 3),
        ]:
            col = QVBoxLayout()
            col.addWidget(label(number, "eyebrow"))
            button = role(QPushButton(title + "  →"), "link")
            button.clicked.connect(lambda checked=False, i=index: self.navigate(i))
            col.addWidget(button)
            col.addWidget(label(hint, "muted"))
            row.addLayout(col, 1)
        content.addLayout(row)
        layout.addWidget(frame)
        layout.addStretch()
        self._set_busy(False)

    def _set_busy(self, busy: bool):
        self.new_button.setEnabled(not busy)
        self.open_button.setEnabled(not busy)
        self.diagnose_button.setEnabled(self.project is not None and not busy)
        self.backup_button.setEnabled(self.project is not None and not busy)

    def set_project(self, project: Project):
        self.project = project
        self.project_name.setText(project.name)
        self.project_details.setText(
            f"저장 위치  {project.root}\n프로젝트 ID  {project.project_id}\n생성 시각 (UTC)  {project.created_at}"
        )
        self.result.setText("프로젝트를 열었습니다. 점검으로 DB 상태를 확인할 수 있습니다.")
        self._set_busy(False)

    def _error(self, exc: Exception):
        QMessageBox.warning(self, "작업을 완료하지 못했습니다", explain_error(str(exc)))

    def _new_project(self):
        parent = QFileDialog.getExistingDirectory(self, "새 작업 폴더를 만들 로컬 위치 선택")
        if not parent:
            return
        name, ok = QInputDialog.getText(self, "새 프로젝트", "프로젝트 이름")
        if not ok:
            return
        try:
            # Human-readable project name stays in DB; folder name is portable.
            path = Path(parent) / f"llm-change-{uuid4().hex[:12]}"
            self.perform_project_operation(lambda: create_project(path, name), self.set_project)
        except Exception as exc:
            self._error(exc)

    def _open_project(self):
        path = QFileDialog.getExistingDirectory(self, "project.db가 있는 작업 폴더 선택")
        if path:
            try:
                self.perform_project_operation(lambda: open_project(Path(path)), self.set_project)
            except Exception as exc:
                self._error(exc)

    def _backup(self):
        if self.project is None:
            return
        try:
            project = self.project
            self.perform_project_operation(
                lambda: backup_project(project),
                lambda destination: self.result.setText(f"DB 백업 완료\n{destination}"),
            )
        except Exception as exc:
            self._error(exc)

    def start_diagnosis(self):
        if self.project is None or self.process is not None:
            return
        self._set_busy(True)
        self.result.setText("프로젝트 점검 중…")
        self.worker_timed_out = False
        self.process = QProcess(self)
        self.process.setProgram(sys.executable)
        self.report_dir = Path(tempfile.mkdtemp(prefix="llm-change-diagnose-"))
        self.process.setArguments(
            (["--worker"] if getattr(sys, "frozen", False) else ["-m", "llm_change_tool.worker"])
            + [
                "diagnose",
                "--project",
                str(self.project.root),
                "--output",
                str(self.report_dir / "result.json"),
            ]
        )
        self.process.finished.connect(self._worker_finished)
        self.process.errorOccurred.connect(self._worker_error)
        self.worker_timer.start(30_000)
        self.process.start()

    def _worker_timeout(self):
        if self.process:
            self.worker_timed_out = True
            self.process.kill()

    def _worker_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.result.setText("점검 프로세스를 시작할 수 없습니다. 설치 환경을 확인하세요.")
            self._cleanup_worker()

    def _worker_finished(self, exit_code, exit_status):
        if self.process is None:
            return
        try:
            if self.worker_timed_out:
                raise ValueError("점검 제한시간을 초과했습니다. 다시 시도하세요.")
            raw = (self.report_dir / "result.json").read_text(encoding="utf-8")
            message = json.loads(raw)
            if exit_code != 0 or exit_status != QProcess.ExitStatus.NormalExit:
                raise ValueError(message.get("message", "프로젝트 점검에 실패했습니다."))
            if message.get("type") != "completed":
                raise ValueError("잘못된 점검 응답입니다.")
            self.result.setText(
                f"점검 완료 · DB 정상 · 스키마 v{message['result']['schema_version']}"
            )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.result.setText(f"점검 실패: {exc}")
        finally:
            self._cleanup_worker()

    def _cleanup_worker(self):
        self.worker_timer.stop()
        if self.process:
            self.process.deleteLater()
        self.process = None
        if self.report_dir:
            shutil.rmtree(self.report_dir, ignore_errors=True)
            self.report_dir = None
        self._set_busy(False)

    def closeEvent(self, event: QCloseEvent):
        if self.process is not None:
            # The v2 diagnostic is read-only; stopping cannot lose edits.
            self.process.kill()
            self.process.waitForFinished(1000)
        event.accept()
