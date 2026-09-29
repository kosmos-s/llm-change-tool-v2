import json
import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from llm_change_tool import __version__
from llm_change_tool.core.datasets import blocking_issues, import_dataset
from llm_change_tool.core.exporting import export_run, final_gate
from llm_change_tool.core.jobs import (
    RunConfig,
    control_job,
    create_job,
    job_info,
    recover_jobs,
    run_job,
    update_budget,
)
from llm_change_tool.core.labels import prompt_text
from llm_change_tool.core.plans import create_plan
from llm_change_tool.core.reviews import compare_run
from llm_change_tool.storage.store import one, rows, transaction
from llm_change_tool.ui.components import (
    STATES,
    Foldout,
    ResultPanel,
    card,
    role,
    scroll_page,
    text_label,
    tone,
)
from llm_change_tool.ui.project_window import MainWindow as ProjectWindow
from llm_change_tool.ui.reviewer import ReviewWidget
from llm_change_tool.ui.tasks import Task

PAGES = [
    ("작업 공간", "프로젝트를 준비하고 작업을 이어가세요."),
    ("데이터 · AI 분석", "데이터를 가져온 뒤 분석 작업을 만들고 실행하세요."),
    ("이미지 검수", "두 시점을 비교하고 최종 라벨을 확정하세요."),
    ("품질 · 내보내기", "미완료 검수와 오류를 확인한 뒤 결과를 저장하세요."),
    ("팀 검수 · 복원", "검수 결과를 주고받고 서로 다른 결정을 확인하세요."),
    ("통계 · 모델 평가", "작업 진행과 AI · 사람 · 모델의 평가 결과를 확인하세요."),
]


class MainWindow(ProjectWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"LLM Change Tool v2 · {__version__}")
        self.resize(1480, 960)
        self.active_task = None
        self.job_id = None
        self.run_id = None
        self.job_state = None
        self.job_provider = None
        self.pipeline_buttons = []
        self.task_page = 1
        self.task_error = False
        project_page = self.takeCentralWidget()
        self.tabs = QTabWidget()
        self.tabs.addTab(scroll_page(project_page), "프로젝트")
        self.build_pipeline()
        self.review_widget = ReviewWidget()
        self.tabs.addTab(self.review_widget, "이미지 검수")
        self.build_results()
        from llm_change_tool.ui.analysis_pages import add_pages

        add_pages(self)
        self.build_shell()
        self.refresh_actions()

    def build_shell(self):
        shell = QWidget()
        shell.setObjectName("workspace")
        row = QHBoxLayout(shell)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(224)
        nav = QVBoxLayout(sidebar)
        nav.setContentsMargins(18, 30, 18, 24)
        nav.setSpacing(6)
        nav.addWidget(text_label("LLM Change\nTool v2", "brand"))
        nav.addWidget(text_label("항공영상 변화탐지 검수"))
        nav.addSpacing(32)
        nav.addWidget(text_label("WORKSPACE", "navSection"))
        self.nav_buttons = []
        for index, (title, _) in enumerate(PAGES):
            if index == 4:
                nav.addSpacing(22)
                nav.addWidget(text_label("협업 · 분석", "navSection"))
            prefix = f"{index:02d}  " if index < 4 else "＋  "
            button = role(QPushButton(prefix + title), "nav")
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, i=index: self.navigate(i))
            nav.addWidget(button)
            self.nav_buttons.append(button)
        nav.addStretch()
        nav.addWidget(text_label(f"LOCAL FIRST · {__version__}", "navSection"))
        nav.addWidget(text_label("작업은 내 PC에 저장됩니다.\n원본 파일은 그대로 유지합니다."))
        row.addWidget(sidebar)
        body = QVBoxLayout()
        body.setContentsMargins(26, 26, 26, 20)
        body.setSpacing(18)
        heading = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(4)
        self.page_title = text_label("", "pageTitle")
        self.page_hint = text_label("", "muted")
        titles.addWidget(self.page_title)
        titles.addWidget(self.page_hint)
        heading.addLayout(titles, 1)
        self.project_chip = text_label("프로젝트 선택 전", "badge")
        self.project_chip.setMinimumWidth(180)
        self.project_chip.setMaximumWidth(250)
        heading.addWidget(self.project_chip, alignment=Qt.AlignmentFlag.AlignTop)
        body.addLayout(heading)
        self.tabs.tabBar().hide()
        body.addWidget(self.tabs, 1)
        self.activity = text_label("준비됨 · 왼쪽 메뉴에서 작업 단계를 선택하세요.", "muted")
        body.addWidget(self.activity)
        row.addLayout(body, 1)
        self.setCentralWidget(shell)
        self.tabs.currentChanged.connect(self.update_navigation)
        self.update_navigation(0)

    def navigate(self, index):
        if self.tabs.isTabEnabled(index):
            self.tabs.setCurrentIndex(index)
            self.nav_buttons[index].setFocus(Qt.FocusReason.OtherFocusReason)
        self.update_navigation(self.tabs.currentIndex())

    def update_navigation(self, index):
        if not hasattr(self, "nav_buttons"):
            return
        self.page_title.setText(PAGES[index][0])
        self.page_hint.setText(PAGES[index][1])
        for i, button in enumerate(self.nav_buttons):
            button.setChecked(i == index)

    def button(self, title, fn, layout, *, primary=False, requires="project"):
        button = QPushButton(title)
        if primary:
            role(button, "primary")
        button.setProperty("requires", requires)
        button.clicked.connect(fn)
        layout.addWidget(button)
        self.pipeline_buttons.append(button)
        return button

    def refresh_actions(self):
        busy = bool(self.active_task and self.active_task.isRunning())
        for button in self.pipeline_buttons:
            requires = button.property("requires")
            available = (
                bool(self.run_id)
                if requires == "run"
                else bool(self.project)
                if requires == "project"
                else True
            )
            button.setEnabled(available and not busy)
            button.setToolTip(
                ""
                if available
                else "분석 작업을 먼저 선택하세요."
                if requires == "run"
                else "프로젝트를 먼저 열어 주세요."
            )
        self.pause.setEnabled(self.job_state == "RUNNING")
        self.cancel.setEnabled(
            bool(self.job_id) and self.job_state not in ("COMPLETED", "CANCELLED")
        )
        self.start_button.setEnabled(
            bool(self.job_id) and not busy and self.job_state not in ("COMPLETED", "CANCELLED")
        )
        self.start_button.setText(
            "분석 완료" if self.job_state == "COMPLETED" else "분석 시작 / 이어하기"
        )
        self.reopen_button.setEnabled(
            bool(self.job_id) and not busy and self.job_state == "CANCELLED"
        )
        self.budget_button.setEnabled(
            bool(self.job_id)
            and not busy
            and self.job_provider == "openai"
            and self.job_state in ("PENDING", "PAUSED", "FAILED")
        )
        if hasattr(self, "project_chip"):
            self.retry_button.setEnabled(
                bool(self.job_id) and not busy and self.job_state == "FAILED"
            )
            self.project_chip.setText(self.project.name if self.project else "프로젝트 선택 전")
            self.project_chip.setToolTip(str(self.project.root) if self.project else "")

    def build_pipeline(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        frame, content = card(
            "1  데이터 가져오기",
            "train / val / test를 포함하는 폴더를 선택하세요. 원본 JPG와 JSON은 수정하지 않습니다.",
        )
        bar = QHBoxLayout()
        self.button("데이터 폴더 선택", self.choose_import, bar, primary=True)
        self.dataset_hint = text_label("아직 데이터를 가져오지 않았습니다.", "muted")
        bar.addWidget(self.dataset_hint, 1)
        content.addLayout(bar)
        layout.addWidget(frame)
        frame, content = card(
            "2  새 AI 작업 설정", "시험 분석으로 먼저 확인하거나, 3,000건 본작업을 준비하세요."
        )
        forms = QHBoxLayout()
        left, right = QFormLayout(), QFormLayout()
        self.mode = QComboBox()
        self.mode.addItem("시험용 · 품질 경고 허용 / Mock 가능", "pilot")
        self.mode.addItem("본작업 · split별 1,000건", "production")
        self.provider = QComboBox()
        self.provider.addItem("Mock · 무료 시험", "mock")
        self.provider.addItem("OpenAI · 실제 분석", "openai")
        self.provider.setToolTip("mock: API 호출 없는 시험 분석 / openai: 실제 AI 분석")
        self.model = QLineEdit("gpt-4o-mini")
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("API Key · 이 화면의 메모리에만 유지")
        self.price_in, self.price_out, self.budget = (
            QDoubleSpinBox(),
            QDoubleSpinBox(),
            QDoubleSpinBox(),
        )
        for spin in (self.price_in, self.price_out, self.budget):
            spin.setRange(0, 1000)
            spin.setDecimals(4)
            spin.setPrefix("$ ")
            spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.budget.setValue(5)
        self.policy = QComboBox()
        self.policy.addItem("기본 · 불일치 중심으로 검수", "core")
        self.policy.addItem("상세 · 낮은 신뢰도도 검수", "detailed")
        left.addRow("작업 범위", self.mode)
        left.addRow("AI 공급자", self.provider)
        right.addRow("검수 정책", self.policy)
        right.addRow("예상 비용 한도", self.budget)
        forms.addLayout(left, 1)
        forms.addSpacing(20)
        forms.addLayout(right, 1)
        content.addLayout(forms)
        self.api_settings = QWidget()
        api = QFormLayout(self.api_settings)
        api.setContentsMargins(0, 8, 0, 0)
        api.addRow("모델", self.model)
        api.addRow("API Key", self.key)
        prices = QHBoxLayout()
        prices.addWidget(text_label("입력 / 1M 토큰"))
        prices.addWidget(self.price_in)
        prices.addWidget(text_label("출력 / 1M 토큰"))
        prices.addWidget(self.price_out)
        api.addRow("현재 단가 (USD)", prices)
        self.approve_api = QCheckBox("선택한 이미지를 OpenAI로 전송하고 유료 분석을 실행합니다.")
        api.addRow(self.approve_api)
        self.api_settings.hide()
        content.addWidget(self.api_settings)
        self.provider.currentIndexChanged.connect(self.provider_changed)
        self.provider_changed()
        self.prompt = QTextEdit()
        self.prompt.setPlainText(prompt_text())
        self.prompt.setMinimumHeight(170)
        content.addWidget(Foldout("고급 설정 · 분석 프롬프트", self.prompt))
        bar = QHBoxLayout()
        self.button("이 설정으로 작업 만들기", self.new_job, bar, primary=True)
        bar.addWidget(text_label("작업 생성만으로 API가 호출되지는 않습니다.", "muted"), 1)
        content.addLayout(bar)
        layout.addWidget(frame)
        frame, content = card("3  분석 실행 · 검수로 이동")
        bar = QHBoxLayout()
        self.jobs = QComboBox()
        self.jobs.setMinimumContentsLength(20)
        self.jobs.currentIndexChanged.connect(self.select_job)
        self.jobs.setPlaceholderText("만들어진 분석 작업이 여기에 표시됩니다.")
        bar.addWidget(self.jobs, 1)
        self.button("목록 새로고침", self.refresh_jobs, bar)
        content.addLayout(bar)
        self.selected_run_hint = text_label(
            "생성된 작업은 당시의 모델·프롬프트·비용 설정으로 실행됩니다.", "muted"
        )
        content.addWidget(self.selected_run_hint)
        budget_bar = QHBoxLayout()
        self.budget_button = self.button(
            "선택 작업 예산 변경", self.change_budget, budget_bar, requires="run"
        )
        budget_bar.addWidget(text_label("완료 결과를 유지하며 예산만 변경합니다.", "muted"), 1)
        self.retry_button = self.button(
            "실패 항목 재시도 준비", lambda: self.control("retry"), budget_bar, requires="run"
        )
        content.addLayout(budget_bar)
        bar = QHBoxLayout()
        self.start_button = self.button(
            "분석 시작 / 이어하기", self.start_job, bar, primary=True, requires="run"
        )
        self.pause = QPushButton("일시정지")
        self.pause.clicked.connect(lambda: self.control("pause"))
        self.cancel = role(QPushButton("취소"), "danger")
        self.cancel.clicked.connect(lambda: self.control("cancel"))
        bar.addWidget(self.pause)
        bar.addWidget(self.cancel)
        bar.addStretch()
        self.button("비교하고 검수하기  →", self.compare, bar, requires="run")
        content.addLayout(bar)
        recovery = QWidget()
        recovery_bar = QHBoxLayout(recovery)
        recovery_bar.setContentsMargins(0, 0, 0, 0)
        self.button(
            "실패 항목 재시도 준비", lambda: self.control("retry"), recovery_bar, requires="run"
        )
        self.button(
            "강제 종료된 작업 복구",
            lambda: self.background(lambda p: recover_jobs(self.project)),
            recovery_bar,
        )
        self.reopen_button = self.button(
            "취소 작업 다시 열기", lambda: self.control("reopen"), recovery_bar, requires="run"
        )
        recovery_bar.addStretch()
        content.addWidget(Foldout("재시도 · 중단 작업 복구", recovery))
        layout.addWidget(frame)
        self.log = ResultPanel("데이터를 가져오거나 분석을 실행하면 진행 상태가 표시됩니다.")
        layout.addWidget(self.log)
        layout.addStretch()
        self.tabs.addTab(scroll_page(page), "데이터 · AI 작업")

    def provider_changed(self, *args):
        live = self.provider.currentData() == "openai"
        self.api_settings.setVisible(live)
        self.budget.setEnabled(live)

    def build_results(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        frame, content = card(
            "최종 결과를 저장하기 전",
            "분석 성공, 검수 누락, 보류, 데이터 오류를 한 번에 확인합니다.",
        )
        hint = text_label("필수 검수가 끝나지 않은 항목은 원본으로 대신 저장되지 않습니다.")
        tone(hint, "info")
        content.addWidget(hint)
        bar = QHBoxLayout()
        self.button(
            "1  품질 확인",
            lambda: self.background(lambda p: final_gate(self.project, self.run_id)),
            bar,
            primary=True,
            requires="run",
        )
        self.button(
            "2  최종 결과 내보내기",
            lambda: self.background(lambda p: export_run(self.project, self.run_id)),
            bar,
            requires="run",
        )
        bar.addStretch()
        content.addLayout(bar)
        content.addWidget(
            text_label(
                "시험용은 pilot, 본작업은 production으로 구분해 JPG · JSON · manifest를 새 폴더에 저장합니다.",
                "muted",
            )
        )
        layout.addWidget(frame)
        self.results = ResultPanel(
            "‘품질 확인’을 누르면 내보내기 가능 여부와 남은 항목이 표시됩니다."
        )
        layout.addWidget(self.results)
        layout.addStretch()
        self.tabs.addTab(scroll_page(page), "품질 · Export")

    def set_project(self, project):
        if hasattr(self, "review_widget") and not self.review_widget.bind(None, None):
            return
        super().set_project(project)
        if hasattr(self, "jobs"):
            self.job_id = None
            self.run_id = None
            self.log.reset()
            self.results.reset()
            self.team_result.reset()
            self.analysis.reset()
            self.refresh_jobs()

    def perform_project_operation(self, function, after):
        self.background(lambda progress: function(), after, require_project=False)

    def background(self, function, after=None, *, require_project=True):
        if require_project and not self.project:
            return self._error(ValueError("프로젝트를 먼저 여세요."))
        if self.process is not None or (self.active_task and self.active_task.isRunning()):
            return
        if not self.review_widget.flush():
            return
        if self.active_task:
            self.active_task.deleteLater()
        self.task_page = self.tabs.currentIndex()
        self.task_error = False
        self.activity.setText("작업 중 · 현재 단계가 끝날 때까지 잠시 기다려 주세요.")
        self.active_task = Task(function, self)
        for button in self.pipeline_buttons:
            button.setEnabled(False)
        self.tabs.setTabEnabled(2, False)
        self._set_busy(True)
        self.jobs.setEnabled(False)
        self.active_task.progress.connect(self.show_progress)
        self.active_task.done.connect(lambda value: self.task_done(value, after))
        self.active_task.failed.connect(lambda message: self.task_done({"error": message}, None))
        self.active_task.finished.connect(self.task_finished)
        self.active_task.start()

    def show_progress(self, value):
        if isinstance(value, dict) and "state" in value:
            self.job_state = value["state"]
            self.job_provider = value.get("provider")
            self.refresh_actions()
            if "cost_limit" in value:
                self.selected_run_hint.setText(
                    f"선택 작업 · {value['provider']} / {value['model']} · 예산 ${value['cost_limit']:.4f} · 모델·프롬프트 유지"
                )
        message = self.log.set_result(value)
        if hasattr(self, "activity"):
            self.activity.setText(message)

    def task_done(self, value, after):
        self.task_error = isinstance(value, dict) and "error" in value
        self.show_progress(value)
        if self.task_page == 3:
            self.results.set_result(value)
        elif self.task_page == 4:
            self.team_result.set_result(value)
        elif self.task_page == 5:
            self.analysis.set_result(value)
        if isinstance(value, dict) and "samples" in value and "errors" in value:
            self.dataset_hint.setText(
                f"{value['samples']:,}건 · 시험용 차단 {len(blocking_issues(value['errors'], 'pilot')):,}건 · "
                f"품질 확인 사항 {len(value['errors']):,}건 (본작업은 엄격 검사)"
            )
        if after:
            try:
                after(value)
            except Exception as exc:
                self.task_error = True
                self.activity.setText("결과를 표시하지 못했습니다: " + str(exc))
        if self.task_page == 0 and self.task_error:
            self.result.setText(self.log.summary.text())
        if self.task_error:
            target = self.tabs.widget(self.task_page)
            if hasattr(target, "ensureWidgetVisible"):
                panel = {1: self.log, 3: self.results, 4: self.team_result, 5: self.analysis}.get(
                    self.task_page
                )
                if panel:
                    target.ensureWidgetVisible(panel)

    def task_finished(self):
        self.tabs.setTabEnabled(2, True)
        self._set_busy(False)
        self.jobs.setEnabled(True)
        # QThread.finished is delivered after isRunning() becomes false.
        self.refresh_actions()

    def choose_import(self):
        path = QFileDialog.getExistingDirectory(self, "train/val/test를 포함하는 데이터 루트 선택")
        if path:
            self.background(lambda p: import_dataset(self.project, Path(path), p))

    def new_job(self):
        try:
            config = RunConfig(
                provider=self.provider.currentData(),
                model=self.model.text().strip(),
                input_price=self.price_in.value(),
                output_price=self.price_out.value(),
                cost_limit=self.budget.value(),
                review_policy=self.policy.currentData(),
            )
            mode = self.mode.currentData()
            prompt = self.prompt.toPlainText()
            self.background(
                lambda p: create_job(self.project, create_plan(self.project, mode), config, prompt),
                lambda value: self.refresh_jobs(value),
            )
        except Exception as exc:
            self._error(exc)

    def refresh_jobs(self, select=None):
        if not self.project:
            return
        with transaction(self.project) as con:
            jobs = rows(
                con,
                "SELECT j.*,r.created_at,r.config FROM jobs j JOIN llm_runs r ON r.id=j.run_id ORDER BY r.created_at DESC",
            )
            count = one(con, "SELECT count(*) AS n FROM samples")["n"]
            datasets = rows(con, "SELECT quality FROM datasets")
        issues = json.loads(datasets[0]["quality"]) if datasets else []
        errors = len(issues)
        fatal = len(blocking_issues(issues, "pilot"))
        self.dataset_hint.setText(
            f"{count:,}건 · 시험용 차단 {fatal:,}건 · 품질 확인 사항 {errors:,}건"
            if count
            else "아직 데이터를 가져오지 않았습니다."
        )
        current = select or self.job_id
        self.jobs.blockSignals(True)
        self.jobs.clear()
        for job in jobs:
            config = json.loads(job["config"])
            self.jobs.addItem(
                f"{STATES.get(job['state'], job['state'])} · {config['provider']} · {job['created_at'][:16]}",
                job["id"],
            )
        index = self.jobs.findData(current)
        self.jobs.setCurrentIndex(index if index >= 0 else 0 if jobs else -1)
        self.jobs.blockSignals(False)
        self.select_job()
        self.refresh_actions()

    def select_job(self, *args):
        if not self.project:
            return
        candidate = self.jobs.currentData()
        if candidate:
            with transaction(self.project) as con:
                selected = one(
                    con,
                    """SELECT r.id AS run_id,r.config,r.prompt,p.mode
                    FROM jobs j JOIN llm_runs r ON r.id=j.run_id
                    JOIN work_plans p ON p.id=r.plan_id WHERE j.id=:id""",
                    id=candidate,
                )
                run_id = selected["run_id"]
            if not self.review_widget.bind(self.project, run_id):
                self.jobs.blockSignals(True)
                self.jobs.setCurrentIndex(self.jobs.findData(self.job_id))
                self.jobs.blockSignals(False)
                return
            config = json.loads(selected["config"])
            if self.run_id != run_id:
                self.provider.setCurrentIndex(self.provider.findData(config["provider"]))
                self.mode.setCurrentIndex(self.mode.findData(selected["mode"]))
                self.model.setText(config["model"])
                self.price_in.setValue(config["input_price"])
                self.price_out.setValue(config["output_price"])
                self.budget.setValue(config["cost_limit"])
                self.policy.setCurrentIndex(self.policy.findData(config["review_policy"]))
                self.prompt.setPlainText(selected["prompt"])
                self.results.reset()
                self.analysis.reset()
            self.selected_run_hint.setText(
                f"선택한 작업 · {config['provider']} / {config['model']} · 한도 ${config['cost_limit']:.2f} · 생성 당시 설정으로 실행"
            )
            self.job_id, self.run_id = candidate, run_id
            self.show_progress(job_info(self.project, self.job_id))
        else:
            self.job_id = self.run_id = self.job_state = None
            self.selected_run_hint.setText("작업을 만든 뒤 분석을 시작하세요.")
            self.review_widget.bind(None, None)
        self.refresh_actions()

    def start_job(self):
        if not self.job_id:
            return
        with transaction(self.project) as con:
            run = one(con, "SELECT config FROM llm_runs WHERE id=:id", id=self.run_id)
        if json.loads(run["config"])["provider"] == "openai":
            self.api_settings.show()
            if not self.approve_api.isChecked():
                return self._error(
                    ValueError(
                        "선택한 작업은 OpenAI 분석입니다. API 설정의 이미지 전송/유료 호출 체크를 확인하세요."
                    )
                )
        key = self.key.text().strip() or os.environ.get("OPENAI_API_KEY", "")
        self.background(lambda p: run_job(self.project, self.job_id, key, progress=p))

    def control(self, action):
        if self.job_id:
            try:
                control_job(self.project, self.job_id, action)
                self.show_progress(job_info(self.project, self.job_id))
            except Exception as exc:
                self._error(exc)

    def change_budget(self):
        if not self.job_id:
            return
        current = job_info(self.project, self.job_id)["cost_limit"]
        limit, ok = QInputDialog.getDouble(
            self,
            "선택 작업 예산 변경",
            "새 누적 한도 (USD) · 기존 사용액 포함",
            current,
            0.0001,
            1000,
            4,
        )
        if not ok:
            return
        reason, ok = QInputDialog.getText(self, "예산 변경 이력", "변경 사유")
        if ok:
            job_id = self.job_id
            self.background(
                lambda p: update_budget(
                    self.project, job_id, limit, expected_limit=current, reason=reason
                )
            )

    def compare(self):
        if self.run_id:
            self.background(
                lambda p: compare_run(self.project, self.run_id),
                self.open_reviews,
            )

    def open_reviews(self, value):
        if self.review_widget.bind(self.project, self.run_id):
            self.tabs.setTabEnabled(2, True)
            self.navigate(2)

    def closeEvent(self, event):
        if self.active_task and self.active_task.isRunning():
            if self.job_id:
                self.control("pause")
            QMessageBox.information(
                self,
                "작업 정리 중",
                "작업이 안전하게 멈춘 뒤 닫아 주세요. AI 호출 중이면 현재 요청이 끝날 때까지 기다립니다.",
            )
            event.ignore()
            return
        if self.review_widget.task and self.review_widget.task.isRunning():
            event.ignore()
            return
        if not self.review_widget.flush():
            event.ignore()
            return
        super().closeEvent(event)
