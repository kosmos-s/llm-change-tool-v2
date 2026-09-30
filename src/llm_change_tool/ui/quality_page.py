"""Quality inventory, duplicate comparison and reviewed dataset preparation."""

from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from llm_change_tool.core.labels import FIELDS
from llm_change_tool.core.quality import (
    preparation_preview,
    prepare_dataset,
    quality_report,
    set_exclusion,
)
from llm_change_tool.ui.components import ResultPanel, scroll_page, text_label

ISSUE_TITLES = {
    "split_leakage": "split 간 동일 이미지",
    "duplicate_image": "동일 split 중복",
    "source_labels": "원본 라벨 누락·모순",
    "orphan_image": "JSON 없는 이미지",
}


def label_summary(labels):
    if labels is None:
        return "미검수"
    values = [
        f["title"] + (": 미확정" if labels.get(f["key"]) is None else ": 변화")
        for f in FIELDS
        if labels.get(f["key"]) in (1, None)
    ]
    return ", ".join(values) or "모든 항목 변화 없음"


class QualityPage(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.report = None
        self.context = None
        layout = QVBoxLayout(self)
        layout.addWidget(
            text_label(
                "품질 문제를 확인하고, 수정·제외 이력을 남긴 새 데이터셋을 준비합니다. 원본은 바꾸지 않습니다.",
                "muted",
            )
        )
        bar = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItem("시험용 기준", "pilot")
        self.mode.addItem("본작업 기준", "production")
        bar.addWidget(self.mode)
        window.button("품질 목록 새로고침", self.refresh, bar)
        self.kind = QComboBox()
        self.kind.addItem("모든 유형", "all")
        self.kind.currentIndexChanged.connect(self.render_issues)
        bar.addWidget(self.kind)
        layout.addLayout(bar)
        self.summary = text_label("데이터를 가져온 뒤 새로고침하세요.", "reviewSummary")
        layout.addWidget(self.summary)
        tabs = QTabWidget()
        self.issues = self.table(["등급", "유형", "파일", "상태", "상대 파일 / 상세"])
        self.samples = self.table(["파일", "split", "검수 상태", "준비 제외 사유"])
        self.duplicates = self.table(
            ["그룹", "파일", "split", "원본 라벨", "최종 라벨", "검수 상태"]
        )
        for table, title in [
            (self.issues, "문제 목록"),
            (self.duplicates, "중복 라벨 비교"),
            (self.samples, "포함·제외 선택"),
        ]:
            tabs.addTab(table, title)
            table.cellDoubleClicked.connect(lambda row, col, t=table: self.open_review(t, row))
        layout.addWidget(tabs)
        bar = QHBoxLayout()
        window.button(
            "선택 항목 검수",
            lambda: self.open_review(tabs.currentWidget(), tabs.currentWidget().currentRow()),
            bar,
            requires="run",
        )
        window.button(
            "선택 항목 준비 제외",
            lambda: self.exclude(tabs.currentWidget(), False),
            bar,
            requires="run",
        )
        window.button(
            "제외 취소", lambda: self.exclude(tabs.currentWidget(), True), bar, requires="run"
        )
        layout.addLayout(bar)
        bar = QHBoxLayout()
        window.button(
            "준비 가능 여부 확인",
            lambda: window.background(
                lambda p: preparation_preview(window.project, window.run_id)[0],
                self.result.set_result,
            ),
            bar,
            requires="run",
        )
        window.button("새 데이터셋 만들기", self.prepare, bar, primary=True, requires="run")
        layout.addLayout(bar)
        layout.addWidget(
            text_label(
                "제외는 이 준비 작업에만 적용됩니다. 일반 내보내기 검사는 그대로 유지됩니다. 중복·누수는 대표 항목을 직접 정한 뒤 해결하세요.",
                "muted",
            )
        )
        self.result = ResultPanel("준비 검사 결과와 생성 경로가 여기에 표시됩니다.")
        layout.addWidget(self.result)

    @staticmethod
    def table(headers):
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        table.setMinimumHeight(220)
        return table

    def current_context(self):
        w = self.window
        return (w.project.project_id if w.project else None, w.run_id)

    def clear(self):
        self.context = None
        self.report = None
        for table in (self.issues, self.samples, self.duplicates):
            table.setRowCount(0)
        self.summary.setText("데이터를 가져온 뒤 새로고침하세요.")
        self.result.reset()

    def refresh(self):
        w = self.window
        context = self.current_context()
        mode = self.mode.currentData()

        def done(report):
            if context != self.current_context():
                return
            self.report = report
            self.context = context
            self.kind.blockSignals(True)
            self.kind.clear()
            self.kind.addItem("모든 유형", "all")
            for key in sorted({i["error"] for i in report["issues"]}):
                self.kind.addItem(ISSUE_TITLES.get(key, key), key)
            self.kind.blockSignals(False)
            self.render_issues()
            self.fill(
                self.samples,
                [
                    (
                        s["id"],
                        [
                            s["logical_key"],
                            s["split"],
                            s["review_state"] or "미검수",
                            s["excluded"] or "포함",
                        ],
                    )
                    for s in report["samples"]
                ],
            )
            entries = []
            for group, members in enumerate(report["duplicates"], 1):
                for s in members:
                    entries.append(
                        (
                            s["id"],
                            [
                                group,
                                s["logical_key"],
                                s["split"],
                                label_summary(s["original_labels"]),
                                label_summary(s["final_labels"]),
                                s["review_state"] or "미검수",
                            ],
                        )
                    )
            self.fill(self.duplicates, entries)
            self.summary.setText(
                f"차단 {report['fatal']} · 경고 {report['warnings']} · 중복 그룹 {len(report['duplicates'])}"
            )

        w.background(lambda p: quality_report(w.project, w.run_id, mode), done)

    @staticmethod
    def fill(table, entries):
        table.setRowCount(len(entries))
        for row, (sid, values) in enumerate(entries):
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                item.setData(Qt.ItemDataRole.UserRole, sid)
                table.setItem(row, col, item)

    def render_issues(self):
        if not self.report:
            return
        kind = self.kind.currentData()
        self.fill(
            self.issues,
            [
                (
                    i["sample_id"],
                    [
                        "차단" if i["severity"] == "FATAL" else "경고",
                        ISSUE_TITLES.get(i["error"], i["error"]),
                        i.get("path", ""),
                        i["status"],
                        i.get("other") or str(i.get("details", "")),
                    ],
                )
                for i in self.report["issues"]
                if kind == "all" or i["error"] == kind
            ],
        )

    def selected(self, table, row):
        if self.context != self.current_context():
            self.window._error(ValueError("작업이 변경되었습니다. 품질 목록을 새로고침하세요."))
            return None
        item = table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def open_review(self, table, row):
        sid = self.selected(table, row)
        w = self.window
        if not sid or not w.run_id:
            return
        view = w.review_widget
        if not view.flush():
            return
        view.filter.blockSignals(True)
        view.filter.setCurrentIndex(view.filter.findData("all"))
        view.filter.blockSignals(False)
        from llm_change_tool.core.reviews import review_queue

        items = review_queue(w.project, w.run_id)
        index = next((i for i, s in enumerate(items) if s["id"] == sid), None)
        if index is None:
            return w._error(
                ValueError("선택한 작업에 비교 결과가 없습니다. 분석·비교를 먼저 실행하세요.")
            )
        if view.task and view.task.isRunning():
            return
        view.items = items
        view.index = index
        view.load_current()
        w.navigate(2)

    def exclude(self, table, restore):
        sid = self.selected(table, table.currentRow())
        w = self.window
        if not sid or not w.run_id:
            return
        reason = None
        if not restore:
            reason, ok = QInputDialog.getText(
                self, "준비에서 제외", "사유 (예: 같은 이미지의 train 복사본 제외, test 보존)"
            )
            if not ok:
                return

        def done(value):
            self.result.set_result(value)
            self.context = None
            self.summary.setText("제외 설정 저장됨 · 품질 목록을 새로고침하세요.")

        w.background(lambda p: set_exclusion(w.project, w.run_id, sid, reason), done)

    def prepare(self):
        parent = QFileDialog.getExistingDirectory(self, "새 데이터셋을 만들 부모 폴더")
        if not parent:
            return
        target = Path(parent) / ("prepared-" + uuid4().hex[:10])
        w = self.window
        w.background(lambda p: prepare_dataset(w.project, w.run_id, target), self.result.set_result)


def add_quality_page(window):
    window.quality_page = QualityPage(window)
    window.tabs.addTab(scroll_page(window.quality_page), "데이터 품질 · 준비")
