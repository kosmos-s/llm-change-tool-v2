"""Small native widgets shared by the desktop pages."""

import json
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from llm_change_tool.ui.feedback import explain_error

STATES = {
    "PENDING": "대기",
    "RUNNING": "분석 중",
    "PAUSED": "일시정지",
    "FAILED": "실패",
    "COMPLETED": "완료",
    "CANCELLED": "취소",
    "DONE": "검수 완료",
    "DRAFT": "임시 저장",
    "DEFERRED": "보류",
}
FIELDS = {
    "compared": "비교 완료",
    "required": "필수 검수 대상",
    "sample_total": "전체 데이터",
    "AI_success": "AI 분석 완료",
    "AI_failed": "AI 오류",
    "pending": "대기",
    "running": "처리 중",
    "compare_complete": "비교 완료",
    "review_required": "필수 검수 대상",
    "review_completed": "검수 완료",
    "deferred": "보류",
    "drafts": "임시 저장",
    "modified": "라벨 수정",
    "original_kept": "원본 유지",
    "GPT_human_agreement": "AI · 사람 일치율",
    "input_tokens": "입력 토큰",
    "output_tokens": "출력 토큰",
    "estimated_cost": "예상 사용액 (USD)",
    "unresolved_reserve": "미확정 예약액 (USD)",
    "total": "계획 항목",
    "ai_success": "AI 성공",
    "human_complete": "사람 검수 완료",
    "english_reason_missing": "영문 근거 미입력 (선택 항목)",
    "review_decisions": "최종 결정 완료",
}


def text_label(text="", name="", wrap=True):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(wrap)
    widget.setObjectName(name)
    return widget


def tone(widget, value):
    widget.setProperty("tone", value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.setMinimumHeight(40)
    widget.updateGeometry()


def role(button, value):
    button.setProperty("role", value)
    return button


def card(title, description=""):
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(20, 18, 20, 18)
    layout.setSpacing(12)
    layout.addWidget(text_label(title, "sectionTitle"))
    if description:
        layout.addWidget(text_label(description, "muted"))
    return frame, layout


def scroll_page(widget):
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setWidget(widget)
    return area


class Foldout(QWidget):
    def __init__(self, title, content):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.toggle = role(QPushButton("＋  " + title), "link")
        self.toggle.setCheckable(True)
        self.content = content
        self.content.setVisible(False)
        self.toggle.toggled.connect(lambda checked: self.content.setVisible(checked))
        self.toggle.toggled.connect(
            lambda checked: self.toggle.setText(("－  " if checked else "＋  ") + title)
        )
        layout.addWidget(self.toggle)
        layout.addWidget(content)


def table(headers):
    result = QTableWidget(0, len(headers))
    result.setHorizontalHeaderLabels(headers)
    result.verticalHeader().hide()
    result.setAlternatingRowColors(True)
    result.setShowGrid(False)
    result.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    result.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    result.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    result.verticalHeader().setDefaultSectionSize(36)
    result.setMinimumHeight(160)
    return result


class ResultPanel(QFrame):
    """Human-readable feedback first; raw diagnostic JSON remains expandable."""

    def __init__(self, empty="작업을 실행하면 결과가 여기에 표시됩니다."):
        super().__init__()
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        self.empty_text = empty
        self.summary = text_label(empty)
        tone(self.summary, "info")
        layout.addWidget(self.summary)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.values = table(["항목", "결과"])
        self.values.hide()
        layout.addWidget(self.values)
        self.open_folder = QPushButton("저장 폴더 열기  ↗")
        self.open_folder.hide()
        self.output_path = None
        self.open_folder.clicked.connect(self.open_output)
        layout.addWidget(self.open_folder, alignment=Qt.AlignmentFlag.AlignLeft)
        self.raw = QTextEdit()
        self.raw.setReadOnly(True)
        self.raw.setMinimumHeight(130)
        self.raw.setMaximumHeight(220)
        layout.addWidget(Foldout("상세 기록 보기", self.raw))

    def reset(self):
        self.summary.setText(self.empty_text)
        tone(self.summary, "info")
        self.values.setRowCount(0)
        self.values.hide()
        self.progress.hide()
        self.raw.clear()
        self.output_path = None
        self.open_folder.hide()

    def open_output(self):
        if self.output_path:
            path = Path(self.output_path)
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(path if path.is_dir() else path.parent))
            )

    def set_result(self, value):
        self.raw.setPlainText(json.dumps(value, ensure_ascii=False, indent=2, default=str))
        rows, level, summary = [], "success", "작업이 완료되었습니다."
        self.progress.hide()
        self.output_path = None
        if isinstance(value, dict):
            if "error" in value:
                summary, level = "작업을 완료하지 못했습니다.\n" + str(value["error"]), "error"
            elif "passed" in value:
                summary = (
                    "품질 확인 통과 · 결과를 내보낼 수 있습니다."
                    if value["passed"]
                    else f"내보내기 보류 · 확인할 항목 {len(value.get('problems', [])):,}개"
                )
                level = "success" if value["passed"] else "warning"
                reasons = {
                    "required human review unresolved": "필수 검수를 완료해 주세요.",
                    "deferred/draft/stale human review": "보류·초안 또는 이전 결과의 검수를 다시 확인해 주세요.",
                    "unresolved API error or missing success": "AI 오류를 해결하고 분석을 완료해 주세요.",
                    "missing comparison/review-list entry": "비교를 실행해 검수 목록을 만들어 주세요.",
                    "stale comparison": "현재 AI 결과로 비교를 다시 실행해 주세요.",
                    "AI job is not COMPLETED": "AI 분석을 먼저 완료해 주세요.",
                    "malformed output": "AI 응답 형식이 올바르지 않습니다.",
                }
                for problem in value.get("problems", []):
                    parts = str(problem).rsplit(": ", 1)
                    key, detail = parts if len(parts) == 2 else ("작업 상태", parts[0])
                    rows.append((key, reasons.get(detail, detail)))
                rows += [(FIELDS.get(k, k), str(v)) for k, v in value.get("counts", {}).items()]
            elif "counts" in value and "state" in value:
                counts = value["counts"]
                total = sum(counts.values())
                done = counts.get("COMPLETED", 0)
                summary = f"{STATES.get(value['state'], value['state'])} · {done:,} / {total:,}건 분석 완료"
                if value.get("message"):
                    summary += "\n" + explain_error(value["message"])
                level = "warning" if value["state"] in ("FAILED", "PAUSED") else "info"
                self.progress.setRange(0, max(total, 1))
                self.progress.setValue(done)
                self.progress.show()
                rows = [(STATES.get(k, k), f"{v:,}건") for k, v in counts.items()]
                usage = value.get("usage", {})
                rows += [
                    (
                        "예상 사용액 / 예약액",
                        f"${usage.get('cost', 0):.4f} / ${usage.get('reserved', 0):.4f}",
                    )
                ]
                if "cost_limit" in value:
                    rows.append(("현재 누적 예산 한도", f"${value['cost_limit']:.4f}"))
                for failure in value.get("failures", []):
                    rows.append((f"실패 {failure['count']:,}건", explain_error(failure["error"])))
            elif "current" in value and "total" in value:
                summary, level = (
                    f"데이터 확인 중 · {value['current']:,} / {value['total']:,}건",
                    "info",
                )
                self.progress.setRange(0, max(value["total"], 1))
                self.progress.setValue(value["current"])
                self.progress.show()
            elif "errors" in value and "samples" in value:
                count = len(value["errors"])
                summary = f"데이터 {value['samples']:,}건 확인 · 품질 확인 사항 {count:,}건"
                level = "warning" if count else "success"
                rows = [(e.get("path", "데이터"), e.get("error", "")) for e in value["errors"]]
                if not count:
                    summary += "\n이제 AI 작업을 만들고 분석을 시작하세요."
            elif "ready" in value and "split_counts" in value:
                ready = value["ready"]
                level = "success" if ready else "warning"
                summary = (
                    "데이터 복사본 준비 가능"
                    if ready
                    else "데이터 준비 차단 · 아래 항목을 해결하세요."
                )
                if "path" in value:
                    self.output_path = str(value["path"])
                    summary = "새 데이터셋 생성 및 재검사 완료\n" + self.output_path
                rows = [
                    ("포함 / 제외", f"{value['included']} / {value['excluded']}"),
                    (
                        "본작업 최소 수량",
                        "충족" if value["production_size_ready"] else "미달 · split별 1,000건 필요",
                    ),
                ]
                rows += [("해결 필요", str(p)) for p in value.get("problems", [])]
                rows += [(split, f"{count}건") for split, count in value["split_counts"].items()]
            elif "by_error_type" in value:
                summary = "검수 수정률·표본 검사·시간 보고서"
                if "path" in value:
                    self.output_path = str(value["path"])
                rate = value["modification_rate"]
                rows = [
                    ("완료 / 수정", f"{value['completed']} / {value['modified']}"),
                    ("원본 수정률", f"{rate:.1%}" if rate is not None else "미확정"),
                    ("추정 입력 시간", f"{value['estimated_interaction_seconds']:.1f}초"),
                    ("시간 측정 범위", value["timing_note"]),
                ]
                audit = value["auto_audit"]
                observed = audit["observed_error_rate"]
                rows += [
                    ("자동 유지 표본 완료 / 선정", f"{audit['completed']} / {audit['selected']}"),
                    ("완료 표본 오류율", f"{observed:.1%}" if observed is not None else "미확정"),
                ]
                rows += [
                    (key, f"완료 {v['completed']} · 수정 {v['modified']}")
                    for key, v in value["by_error_type"].items()
                ]
                if value.get("selection"):
                    rows.append(("표본 seed", value["selection"]["seed"]))
            elif "audit_selected" in value:
                summary = f"자동 유지 {value['audit_selected']}건을 필수 검수 목록에 추가했습니다."
                rows = [("표본 seed", value["seed"])]
            elif "path" in value:
                self.output_path = str(value["path"])
                summary = "파일 저장 완료\n" + self.output_path
                if "samples" in value:
                    rows = [("저장 항목", f"{value['samples']:,}건")]
            elif any(k in value for k in ("NEW", "SAME", "CONFLICT")):
                summary = "팀 검수 결과를 확인했습니다."
                rows = [
                    (title, str(value.get(key, 0)))
                    for key, title in [
                        ("NEW", "새로 반영"),
                        ("SAME", "동일 결과"),
                        ("CONFLICT", "충돌 · 해결 필요"),
                    ]
                ]
                if value.get("CONFLICT"):
                    level = "warning"
            elif "sample_total" in value:
                summary = "현재 선택한 작업의 진행 현황입니다."
                rows = [(FIELDS[k], self.format_value(k, value[k])) for k in FIELDS if k in value]
            else:
                rows = [
                    (FIELDS.get(k, k), str(v))
                    for k, v in value.items()
                    if isinstance(v, (str, int, float, bool))
                ]
        elif isinstance(value, str):
            summary = "새 작업이 준비되었습니다. ‘분석 시작’을 눌러 진행하세요."
        self.summary.setText(summary)
        tone(self.summary, level)
        self.open_folder.setVisible(self.output_path is not None)
        self.values.setRowCount(len(rows))
        for r, (key, val) in enumerate(rows):
            for column, text in enumerate((key, val)):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self.values.setItem(r, column, item)
        self.values.setVisible(bool(rows))
        self.values.setMinimumHeight(min(240, 42 + len(rows) * 36))
        self.values.setMaximumHeight(min(320, 42 + len(rows) * 36))
        return summary.split("\n")[0]

    @staticmethod
    def format_value(key, value):
        if value is None:
            return "아직 없음"
        if key == "GPT_human_agreement":
            return f"{value:.1%}"
        if "cost" in key or "reserve" in key:
            return f"${value:.4f}"
        return f"{value:,}" if isinstance(value, (int, float)) else str(value)


class DashboardPanel(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        grid = QGridLayout()
        self.metrics = {}
        for index, key in enumerate(
            [
                "sample_total",
                "AI_success",
                "review_required",
                "review_completed",
                "AI_failed",
                "deferred",
                "GPT_human_agreement",
                "estimated_cost",
            ]
        ):
            frame, content = card(FIELDS[key])
            val = text_label("—", "metricValue")
            self.metrics[key] = val
            content.addWidget(val)
            grid.addWidget(frame, index // 4, index % 4)
        layout.addLayout(grid)
        self.metric_table = table(["평가 대상 / 라벨", "Precision", "Recall", "F1", "F2"])
        self.metric_table.setMinimumHeight(300)
        self.metric_table.hide()
        layout.addWidget(self.metric_table)
        self.result = ResultPanel("‘현황 새로고침’을 누르면 선택한 작업의 통계가 표시됩니다.")
        layout.addWidget(self.result)

    def reset(self):
        for val in self.metrics.values():
            val.setText("—")
        self.metric_table.setRowCount(0)
        self.metric_table.hide()
        self.result.reset()

    def set_result(self, value):
        if isinstance(value, dict) and "sample_total" in value:
            for key, val in self.metrics.items():
                val.setText(ResultPanel.format_value(key, value.get(key)))
        from llm_change_tool.core.labels import FIELDS as LABELS

        titles = {f["key"]: f["title"] for f in LABELS}
        reports = (
            value
            if isinstance(value, list)
            else value.get("runs", [])
            if isinstance(value, dict)
            else []
        )
        if isinstance(value, dict) and "VLM_vs_human" in value:
            reports = [{"name": "AI · 사람", **value["VLM_vs_human"]}]
        elif isinstance(value, dict) and "metrics" in value:
            reports = [value]
        cells = []
        for report in reports:
            name = report.get("name", report.get("model", "평가"))
            for key, scores in report.get("metrics", {}).items():
                cells.append(
                    [f"{name} · {titles.get(key, key)}"]
                    + [f"{scores[k]:.1%}" for k in ("precision", "recall", "f1", "f2")]
                )
        self.metric_table.setRowCount(len(cells))
        for r, row in enumerate(cells):
            for c, cell in enumerate(row):
                self.metric_table.setItem(r, c, QTableWidgetItem(cell))
        self.metric_table.setVisible(bool(cells))
        return self.result.set_result(value)
