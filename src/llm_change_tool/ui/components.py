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


def job_progress(counts):
    """Return processed/total progress without treating failures as still pending."""
    total = sum(counts.values())
    completed = counts.get("COMPLETED", 0)
    failed = counts.get("FAILED", 0)
    processed = completed + failed
    percent = processed / total * 100 if total else 0.0
    return processed, total, completed, failed, percent


def percent_text(percent):
    if percent in (0, 100):
        return f"{percent:.0f}%"
    if percent < 1:
        return f"{percent:.2f}%"
    return f"{percent:.1f}%"


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
    if title:
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
        self.progress_detail = text_label("", "muted")
        self.progress_detail.hide()
        layout.addWidget(self.progress_detail)
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
        self.progress_detail.hide()
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
        self.progress_detail.hide()
        self.progress.hide()
        self.output_path = None
        if isinstance(value, dict):
            if "error" in value:
                summary, level = (
                    "작업을 완료하지 못했습니다.\n" + explain_error(value["error"]),
                    "error",
                )
            elif "inventory" in value and "selected_count" in value:
                inventory = value["inventory"]
                summary = f"고유 후보 점검 · 선정 {value['selected_count']:,}건 / 선정 가능 {inventory['eligible_count']:,}건"
                if not value.get("ready", True):
                    summary += "\n목표 수량 부족 · 작업 생성 전 원인을 확인하세요."
                    level = "warning"
                rows = [
                    ("정책", value["policy_version"]),
                    (
                        "등록 / 고유 / 보류",
                        f"{inventory['registered_count']} / {inventory['unique_count']} / {inventory['held_unique_count']}",
                    ),
                    ("중복 등록", str(inventory["duplicate_copies"])),
                    ("선정 원칙", "출처 집단 우선 균형 · 부족 집단 잔여 배분 · FN/FP는 정답 아님"),
                ]
                for split, stat in inventory["split_counts"].items():
                    rows.append(
                        (
                            split,
                            f"등록 {stat['registered']} → 고유 {stat['unique']} → 보류 {stat['held_unique']} → 가능 {stat['eligible']} · 제외 {stat['rejected']} · 목표 {stat['target'] if stat['target'] is not None else '시험용: 해당 없음'} · 부족 {stat['shortage'] if stat['shortage'] is not None else '해당 없음'}",
                        )
                    )
                    rows += [
                        (f"{split} 보류 이유", f"{explain_error(reason)}: {n}")
                        for reason, n in stat["reason_counts"].items()
                    ]
                rows += [
                    ("제외·비연결 파일", f"{r.get('path')}: {explain_error(r.get('error'))}")
                    for r in inventory["rejected"]
                ]
            elif value.get("kind") == "paired_model_comparison":
                delta = value["delta_percentage_points"]
                summary = "변화 유무 F1 전후 비교 · " + (
                    f"{delta:+.2f}%p" if delta is not None else "F1 변화량 정의 불가"
                )
                rows = [
                    ("기준 데이터", value["golden_id"]),
                    (
                        "평가 범위",
                        "고정 test · 내부 기준"
                        if value["final_test_eligible"]
                        else "참고 평가 · 최종 test 성과 아님",
                    ),
                    ("사람 오류 검토", "대기 · CSV의 manual_checked와 manual_notes에 기록하세요."),
                ]
                for key, title in (
                    ("tp", "정탐 TP"),
                    ("fp", "오탐 FP"),
                    ("fn", "미탐 FN"),
                    ("tn", "정상 음성 TN"),
                ):
                    rows.append(
                        (
                            title,
                            f"{value['baseline']['scene'][key]} → {value['candidate']['scene'][key]}",
                        )
                    )
                if "path" in value:
                    self.output_path = str(value["path"])
                    rows.append(("보고서", self.output_path))
                    rows.append(("수동 검토 CSV", value["manual_audit_path"]))
            elif value.get("kind") == "manual_count_check":
                summary = (
                    "수동 집계 일치"
                    if value["matches"]
                    else "수동 집계 불일치 · TP/FP/FN/TN을 다시 확인하세요."
                )
                rows = [
                    ("집계 건수", str(value["total"])),
                    (
                        "수동 집계 F1",
                        f"{value['f1']:.1%}" if value["f1"] is not None else "정의 불가",
                    ),
                    ("확인 범위", "숫자 대조이며 영상 판정의 정확도를 확인한 것은 아닙니다."),
                ]
                level = "success" if value["matches"] else "warning"
            elif "passed" in value:
                summary = (
                    "품질 확인 통과 · 결과를 내보낼 수 있습니다."
                    if value["passed"]
                    else f"내보내기 보류 · 확인할 항목 {len(value.get('problems', [])):,}개"
                )
                level = "success" if value["passed"] else "warning"
                counts = value.get("counts", {})
                summary += f"\n사람 검수 완료 {counts.get('human_complete', 0):,} / {counts.get('total', 0):,}건 · Gate 통과는 전건 사람 검수나 정확도 향상을 뜻하지 않습니다."
                if value.get("legacy_core_pilot"):
                    summary += "\n이전 core 시험용 정책: 낮은 신뢰도만 있는 항목은 자동 유지될 수 있습니다."
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
                    rows.append((key, reasons.get(detail, explain_error(detail))))
                rows += [(FIELDS.get(k, k), str(v)) for k, v in value.get("counts", {}).items()]
            elif "counts" in value and "state" in value:
                counts = value["counts"]
                processed, total, done, failed, percent = job_progress(counts)
                percent_label = percent_text(percent)
                summary = (
                    f"{STATES.get(value['state'], value['state'])} · {percent_label} · "
                    f"{processed:,} / {total:,}건 처리"
                )
                if value.get("message"):
                    summary += "\n" + explain_error(value["message"])
                level = "warning" if value["state"] in ("FAILED", "PAUSED") else "info"
                self.progress.setRange(0, max(total, 1))
                self.progress.setValue(processed)
                self.progress.show()
                self.progress_detail.setText(
                    f"진행률 {percent_label} · 성공 {done:,}건 · 실패 {failed:,}건 · 남음 {max(total - processed, 0):,}건"
                )
                self.progress_detail.show()
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
                    domain_label = {
                        "data": "데이터 오류",
                        "configuration": "인증·설정 오류",
                        "transient": "일시 통신·서버 오류",
                        "ai_response": "AI 응답 오류",
                        "unknown_outcome": "원격 결과·과금 미확정",
                        "provider": "AI 호출 오류",
                    }.get(failure.get("domain"), "분류 미확정")
                    rows.append(
                        (
                            f"실패 {failure['count']:,}건 · {domain_label}",
                            explain_error(failure["error"])
                            + (" · 재시도 가능" if failure.get("retryable") else " · 재시도 불가"),
                        )
                    )
            elif "current" in value and "total" in value:
                percent = value["current"] / value["total"] * 100 if value["total"] else 0
                percent_label = percent_text(percent)
                summary, level = (
                    f"데이터 확인 중 · {percent_label} · {value['current']:,} / {value['total']:,}건",
                    "info",
                )
                self.progress.setRange(0, max(value["total"], 1))
                self.progress.setValue(value["current"])
                self.progress.show()
                self.progress_detail.setText(f"진행률 {percent_label}")
                self.progress_detail.show()
            elif "errors" in value and "samples" in value:
                count = len(value["errors"])
                summary = f"데이터 {value['samples']:,}건 확인 · 품질 확인 사항 {count:,}건"
                level = "warning" if count else "success"
                rows = [
                    (e.get("path", "데이터"), explain_error(e.get("error", "")))
                    for e in value["errors"]
                ]
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
                if value.get("note"):
                    summary += "\n" + value["note"]
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
        self.overall = text_label("변화 유무 F1 · 아직 평가하지 않았습니다.", "reviewSummary")
        self.overall.setToolTip(
            "대표: 주요 5개 라벨 중 하나라도 양성이면 변화 있음으로 계산합니다. 보조: 주요 5개 라벨의 micro F1입니다. 세부 라벨과 도로 표식은 대표·보조 집계에서 제외합니다."
        )
        layout.addWidget(self.overall)
        self.metric_table = table(
            ["평가 대상 / 라벨", "Precision", "Recall", "F1", "F2", "TP", "FP", "FN", "TN"]
        )
        self.metric_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Interactive
        )
        self.metric_table.setColumnWidth(0, 320)
        self.metric_table.setMinimumHeight(300)
        self.metric_table.hide()
        layout.addWidget(self.metric_table)
        self.result = ResultPanel("‘현황 새로고침’을 누르면 선택한 작업의 통계가 표시됩니다.")
        layout.addWidget(self.result)

    def reset(self):
        for val in self.metrics.values():
            val.setText("—")
        self.overall.setText("변화 유무 F1 · 아직 평가하지 않았습니다.")
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
        elif isinstance(value, dict) and value.get("kind") == "paired_model_comparison":
            reports = [value["baseline"], value["candidate"]]
        elif isinstance(value, dict) and "metrics" in value:
            reports = [value]
        from llm_change_tool.core.metrics import overall_metrics

        cells, summaries = [], []
        for report in reports:
            name = report.get("name", report.get("model", "평가"))
            overall = report.get("overall") or overall_metrics(report.get("metrics", {}))
            matched, reference = report.get("matched", 0), report.get("reference", 0)
            scope = f"평가 {matched}/{reference}건"
            if report.get("partial_review"):
                scope = f"부분 평가 {matched}건 · 선택 작업 {report['selected_total']}건 중 검수 완료 항목"
            elif matched != reference:
                scope += " · 예측 누락 있음: 전체 평가 아님"
            if report.get("golden_id"):
                scope += f" · 기준 {report['golden_id'][:8]} / {report.get('split', '미지정')}"
            if report.get("provider") == "mock":
                scope += " · Mock 시험 결과 / 실제 AI 정확도 아님"
            scene = report.get("scene")
            if scene:
                primary = [f"{scene[k]:.1%}" for k in ("precision", "recall", "f1", "f2")]
                if not scene["defined"]:
                    primary = ["—"] * 4
                cells.append(
                    [
                        f"{name} · 대표 변화 유무",
                        *primary,
                        *[str(scene[k]) for k in ("tp", "fp", "fn", "tn")],
                    ]
                )
                summaries.append(
                    f"{name} · 변화 유무 F1 {primary[2]} · {scope}"
                    + (" · 양성·오탐·미탐이 없어 정의할 수 없음" if not scene["defined"] else "")
                )
            else:
                summaries.append(
                    f"{name} · 변화 유무 F1 — · 이전 기록에는 장면 예측이 없습니다. 실제 예측을 다시 가져오세요."
                    if overall
                    else f"{name} · 변화 유무 F1 — · 평가할 정답과 예측이 필요합니다."
                )
            if overall:
                scores = [f"{overall[k]:.1%}" for k in ("precision", "recall", "f1", "f2")]
                if not overall["defined"]:
                    scores = ["—"] * 4
                cells.append(
                    [
                        f"{name} · 보조 종합 (주요 5개 라벨·micro)",
                        *scores,
                        *[str(overall[k]) for k in ("tp", "fp", "fn", "tn")],
                    ]
                )
                summaries.append(
                    f"{name} · 보조 micro F1 {scores[2]} · {scope}"
                    + (
                        " · 변화 양성·오탐·미탐이 없어 F1을 정의할 수 없음"
                        if not overall["defined"]
                        else ""
                    )
                )
            else:
                summaries.append(f"{name} · 종합 F1 — · {scope} · 평가할 정답과 예측이 필요합니다.")
            for key, scores in report.get("metrics", {}).items():
                cells.append(
                    [f"{name} · {titles.get(key, key)}"]
                    + [f"{scores[k]:.1%}" for k in ("precision", "recall", "f1", "f2")]
                    + [str(scores[k]) for k in ("tp", "fp", "fn", "tn")]
                )
        self.overall.setText("\n".join(summaries) or "변화 유무 F1 · 아직 평가하지 않았습니다.")
        self.metric_table.setRowCount(len(cells))
        for r, row in enumerate(cells):
            for c, cell in enumerate(row):
                item = QTableWidgetItem(cell)
                item.setToolTip(cell)
                self.metric_table.setItem(r, c, item)
        self.metric_table.setVisible(bool(cells))
        return self.result.set_result(value)
