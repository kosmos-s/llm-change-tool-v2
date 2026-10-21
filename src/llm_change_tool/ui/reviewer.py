import json
import time
from collections import OrderedDict

from PIL import ImageChops
from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from llm_change_tool.core.datasets import safe_path, sample_images
from llm_change_tool.core.labels import FIELDS, effective_doc, strict_json
from llm_change_tool.core.reviews import (
    BLIND_ORIGIN,
    review_history,
    review_queue,
    review_summary,
    save_review,
    undo_review,
)
from llm_change_tool.ui.components import STATES, Foldout, card, role, scroll_page, text_label, tone
from llm_change_tool.ui.feedback import explain_error
from llm_change_tool.ui.image_view import ImageView
from llm_change_tool.ui.tasks import Task

SIGNALS = {
    "auto_audit": "자동 유지 표본 검수",
    "source_labels": "원본 라벨 누락·모순 — 필수 검수",
    "change_mismatch": "변화 여부 불일치",
    "detail_mismatch": "세부 라벨 불일치",
    "low_confidence": "낮은 신뢰도",
    "review_required": "AI가 검수 요청",
    "malformed_output": "응답 형식 오류",
    "api_error": "AI 호출 오류",
    "API_error": "AI 호출 오류",
    "data_error": "이미지·데이터 오류",
    "configuration_error": "API 인증·모델·결제 설정 오류",
    "transient_error": "일시 통신·서버 오류",
    "unknown_outcome": "원격 결과·과금 미확정",
    "ai_response_error": "AI 응답 오류",
    "pending": "분석 대기",
}


class ReviewWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("KOSMOS", "LLMChangeTool")
        self.image_cache = OrderedDict()
        self.cache_bytes = 0
        self.cache_limit = 64 * 1024 * 1024
        self.pending_save = False
        self.project = None
        self.run_id = None
        self.items = []
        self.index = 0
        self.dirty = False
        self.loading = False
        self.task = None
        self.images = None
        self.loaded_sample_id = None
        self.effort_seconds = 0.0
        self.last_interaction = time.monotonic()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        top = QHBoxLayout()
        top.addWidget(text_label("검수 목록", "muted"))
        self.filter = QComboBox()
        for title, value in [
            ("전체 항목", "all"),
            ("미검수 항목", "unreviewed"),
            ("보류 항목", "deferred"),
            ("필수 검수 항목", "required"),
        ]:
            self.filter.addItem(title, value)
        self.filter.currentIndexChanged.connect(self.reload)
        top.addWidget(self.filter)
        self.reload_button = QPushButton("새로고침")
        self.reload_button.setToolTip("현재 목록과 이미지를 다시 불러옵니다.")
        self.reload_button.clicked.connect(self.reload)
        top.addWidget(self.reload_button)
        self.reviewer = QLineEdit()
        self.reviewer.setPlaceholderText("검수자 이름을 입력하세요")
        self.reviewer.setAccessibleName("검수자 이름")
        self.reviewer.setMaximumWidth(240)
        self.reviewer.setToolTip("이 PC에 기억되어 다음 실행에도 그대로 사용합니다.")
        # Personal PC: the name is entered once and remembered.
        self.reviewer.setText(self.settings.value("reviewer_name", ""))
        self.reviewer.textChanged.connect(self.remember_reviewer)
        top.addWidget(self.reviewer)
        help_button = QPushButton("도움말")
        help_button.clicked.connect(self.show_help)
        top.addWidget(help_button)
        self.auto = QCheckBox("자동 임시 저장")
        self.auto.setToolTip(
            "입력 후 잠시 멈추면 초안을 저장합니다. 완료 처리는 ‘저장’을 눌러 주세요."
        )
        self.auto.setChecked(True)
        top.addWidget(self.auto)
        self.blind = QCheckBox("독립 판정")
        self.blind.setToolTip(
            "원본·AI 라벨과 근거를 숨기고 빈 판정에서 시작합니다. 사람 정답(Golden Set)을 만들 때 사용하세요."
        )
        self.blind.toggled.connect(self.toggle_blind)
        top.addWidget(self.blind)
        top.addStretch()
        self.progress = text_label("항목 없음", "badge")
        top.addWidget(self.progress)
        layout.addLayout(top)
        self.summary = text_label("전체 0 · 필수 검수 남음 0 · 완료 0 · 보류 0", "reviewSummary")
        layout.addWidget(self.summary)
        self.identity = text_label(
            "AI 분석 후 ‘비교하고 검수하기’를 눌러 검수 목록을 만드세요.", "muted"
        )
        self.identity.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.identity)
        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(12)
        # No card title: on 1440×900-class screens every line taken here shrinks the images.
        viewer, vl = card("")
        viewer.setMinimumWidth(300)
        titles = QHBoxLayout()
        titles.addWidget(text_label("T1  과거 영상", "eyebrow"), 1)
        titles.addWidget(text_label("T2  현재 영상", "eyebrow"), 1)
        vl.addLayout(titles)
        pair = QHBoxLayout()
        self.left, self.right = ImageView(), ImageView()
        self.left.placeholder = "T1 · 과거 영상\n검수 항목을 선택하세요"
        self.right.placeholder = "T2 · 현재 영상\n검수 항목을 선택하세요"
        self.left.peer, self.right.peer = self.right, self.left
        pair.addWidget(self.left, 1)
        pair.addWidget(self.right, 1)
        vl.addLayout(pair, 1)
        controls = QHBoxLayout()
        for name, fn in [("화면 맞춤 · F", self.left.fit), ("100%", self.left.actual)]:
            button = QPushButton(name)
            button.clicked.connect(fn)
            controls.addWidget(button)
        controls.addWidget(
            text_label("휠로 확대 · 드래그로 이동 · 두 이미지가 함께 움직입니다.", "muted"), 1
        )
        self.diff = QCheckBox("차이 영상")
        self.diff.toggled.connect(self.show_images)
        controls.addWidget(self.diff)
        self.flicker = QCheckBox("깜박임")
        self.flicker.toggled.connect(self.toggle_flicker)
        controls.addWidget(self.flicker)
        vl.addLayout(controls)
        splitter.addWidget(viewer)
        panel, pl = card("최종 라벨 확정")
        self.label_heading = pl.itemAt(0).widget()
        panel.setMinimumWidth(370)
        pl.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        choices = QHBoxLayout()
        self.original_button = QPushButton("원본 유지")
        self.ai_button = QPushButton("AI 라벨 적용")
        self.edit_button = QPushButton("직접 수정")
        for button, source in [
            (self.original_button, "original"),
            (self.ai_button, "ai"),
            (self.edit_button, "manual"),
        ]:
            button.clicked.connect(lambda checked=False, source=source: self.apply_labels(source))
            choices.addWidget(button)
        self.rest_unchanged_button = QPushButton("나머지 변화 없음")
        self.rest_unchanged_button.setToolTip(
            "Ctrl+0 · 아직 미확정인 라벨만 ‘없음’으로 정합니다. 변화가 보이는 라벨은 먼저 직접 표시하세요."
        )
        self.rest_unchanged_button.clicked.connect(self.mark_undecided_unchanged)
        self.rest_unchanged_button.hide()
        choices.addWidget(self.rest_unchanged_button)
        pl.addLayout(choices)
        self.decision_hint = text_label("라벨 선택 후 ‘저장’으로 확정하세요.", "muted")
        pl.addWidget(self.decision_hint)
        self.labels = QTableWidget(len(FIELDS), 4)
        self.labels.setHorizontalHeaderLabels(["라벨", "원본", "AI", "최종"])
        self.labels.verticalHeader().hide()
        self.labels.verticalHeader().setDefaultSectionSize(32)
        self.labels.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.labels.setShowGrid(False)
        self.labels.setAlternatingRowColors(True)
        self.labels.setFixedHeight(len(FIELDS) * 32 + 48)
        self.labels.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.boxes = {}
        for i, field in enumerate(FIELDS):
            item = QTableWidgetItem(field["title"])
            item.setToolTip(field["key"])
            self.labels.setItem(i, 0, item)
            box = QCheckBox()
            box.setEnabled("fixed" not in field)
            box.setAccessibleName(field["title"] + " 최종 라벨")
            box.setToolTip(
                "최신 가이드라인에서 제외된 항목입니다."
                if "fixed" in field
                else field["title"] + "의 변화 여부"
            )
            box.checkStateChanged.connect(self.changed)
            container = QWidget()
            centered = QHBoxLayout(container)
            centered.setContentsMargins(0, 0, 0, 0)
            centered.setAlignment(Qt.AlignmentFlag.AlignCenter)
            centered.addWidget(box)
            self.labels.setCellWidget(i, 3, container)
            self.boxes[field["key"]] = box
        for i in (1, 2, 3):
            self.labels.setColumnWidth(i, 51)
        self.labels.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.ai_reason = text_label("AI 분석 결과가 여기에 표시됩니다.", "muted")
        self.ai_reason.setMaximumHeight(64)
        pl.addWidget(self.ai_reason)
        pl.addWidget(self.labels)
        self.other_detail = text_label("", "muted")
        self.other_detail.setAccessibleName("최종 기타 설명")
        self.other_detail.setMaximumHeight(55)
        pl.addWidget(self.other_detail)
        notes = QWidget()
        note_layout = QVBoxLayout(notes)
        note_layout.setContentsMargins(0, 0, 0, 0)
        self.ai_details = text_label("", "muted")
        self.ai_details.setMaximumHeight(65)
        note_layout.addWidget(self.ai_details)
        self.reason = QTextEdit()
        self.reason.setPlaceholderText("최종 판단의 근거를 기록하세요.")
        self.reason.setAccessibleName("검수 근거")
        self.reason.setMinimumHeight(65)
        self.reason.setMaximumHeight(90)
        self.reason.textChanged.connect(self.changed)
        note_layout.addWidget(self.reason)
        self.reason_en = QLineEdit()
        self.reason_en.setPlaceholderText("영문 근거 (선택)")
        self.reason_en.setAccessibleName("검수 영문 근거")
        self.reason_en.setToolTip(
            "라벨·한국어 근거를 바꾸면 기존 영문을 비웁니다. 필요한 경우 새 근거를 입력하세요."
        )
        self.reason_en.textChanged.connect(lambda: self.changed(invalidate_english=False))
        note_layout.addWidget(self.reason_en)
        self.notes = Foldout("AI 판단 근거 · 검수 메모", notes)
        pl.addWidget(self.notes)
        self.panel_scroll = scroll_page(panel)
        self.panel_scroll.setMinimumWidth(400)
        splitter.addWidget(self.panel_scroll)
        self.notes.toggle.toggled.connect(
            lambda expanded: (
                QTimer.singleShot(0, lambda: self.panel_scroll.ensureWidgetVisible(self.reason_en))
                if expanded
                else None
            )
        )
        splitter.setSizes([780, 410])
        layout.addWidget(splitter, 1)
        self.signals = text_label("")
        self.signals.hide()
        layout.addWidget(self.signals)
        nav = QHBoxLayout()
        self.buttons = []
        for title, fn, hint in [
            ("← 이전", lambda: self.move(-1), "Alt+Left"),
            ("다음 →", lambda: self.move(1), "Alt+Right"),
            (
                "보류",
                lambda: self.save("DEFERRED", True, asynchronous=True),
                "나중에 다시 검수합니다.",
            ),
            ("되돌리기", self.undo, "Ctrl+Z · 이전 검수 기록으로 복원"),
            ("이력", self.history, "검수자와 수정 기록 확인"),
            ("저장", lambda: self.save(asynchronous=True), "Ctrl+S · 검수 완료"),
            ("저장 후 다음  →", lambda: self.save("DONE", True, asynchronous=True), "Ctrl+Enter"),
        ]:
            if title == "저장":
                nav.addStretch()
            button = QPushButton(title)
            button.clicked.connect(fn)
            button.setToolTip(hint)
            if title.startswith("저장 후"):
                role(button, "primary")
            nav.addWidget(button)
            self.buttons.append(button)
        layout.addLayout(nav)
        self.status = text_label(
            "자동 저장은 초안입니다. ‘저장’을 눌러 검수를 완료하세요.", "muted"
        )
        layout.addWidget(self.status)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(1200)
        self.timer.timeout.connect(lambda: self.autosave(asynchronous=True))
        self.flash = QTimer(self)
        self.flash.setInterval(500)
        self.flash.timeout.connect(self.flash_frame)
        self.flash_index = 0
        self.shortcuts = []
        for key, fn in [
            ("Ctrl+S", lambda: self.save(asynchronous=True)),
            ("Ctrl+Return", lambda: self.save("DONE", True, asynchronous=True)),
            ("Alt+Left", lambda: self.move(-1)),
            ("Alt+Right", lambda: self.move(1)),
            ("Ctrl+Z", self.undo),
            ("F", self.left.fit),
            ("Ctrl+F", self.find_sample),
            ("Ctrl+0", self.mark_undecided_unchanged),
        ]:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(fn)
            self.shortcuts.append((key, shortcut))
        QApplication.instance().focusChanged.connect(self.update_shortcuts)
        self.load_current()

    def update_shortcuts(self, previous, current):
        editing = isinstance(current, (QLineEdit, QTextEdit))
        for key, shortcut in self.shortcuts:
            if key in ("F", "Ctrl+Z"):
                shortcut.setEnabled(not editing)

    def show_help(self):
        QMessageBox.information(
            self,
            "검수 기준 · 단축키",
            (
                "이름 입력 → 영상·라벨 확인 → 근거 입력 → 저장 후 다음\n"
                "저장은 현재 1건의 완료이며 자동 저장은 초안입니다.\n\n"
                "Ctrl+S 저장 · Ctrl+Enter 저장 후 다음\n"
                "Alt+←/→ 이동 · Ctrl+Z 되돌리기 · Ctrl+F 항목 찾기 · F 화면 맞춤\n\n"
                "독립 판정: 원본·AI 라벨을 숨기고 미확정에서 시작합니다. 모든 라벨과\n"
                "판정 근거를 직접 입력해야 완료되며, 기록에 독립 판정으로 남습니다.\n"
                "변화가 보이는 라벨만 표시한 뒤 Ctrl+0(나머지 변화 없음)으로 남은 미확정을\n"
                "‘없음’으로 정할 수 있습니다.\n\n"
                "최신 기준: 도로 표식은 0. 일반 촬영조건 차이는 제외합니다.\n"
                "건물 기울임·수목 계절 변화·농경지 생육 단계는 지침의 예외를 확인하세요.\n"
                "면적 기준: 9분할 한 칸의 인공물 1/2, 수목·산림·농경지 1/4.\n"
                "거리·정합·면적이 불확실하면 보류하고 원문 지침을 확인하세요."
            ),
        )

    def find_sample(self):
        if self.pending_save or (self.task and self.task.isRunning()):
            return
        query, ok = QInputDialog.getText(self, "항목 찾기", "샘플 ID 또는 경로 일부")
        if not ok or not query.strip():
            return
        matches = [
            (i, sample)
            for i, sample in enumerate(self.items)
            if query.strip().casefold() in (sample["id"] + " " + sample["logical_key"]).casefold()
        ]
        if not matches:
            self.status.setText(
                "현재 필터에서 해당 항목을 찾지 못했습니다. 전체 항목 필터를 확인하세요."
            )
            return
        if len(matches) > 1:
            choices = [sample["logical_key"] for _, sample in matches]
            selected, ok = QInputDialog.getItem(self, "항목 선택", "찾은 항목", choices, 0, False)
            if not ok:
                return
            target = matches[choices.index(selected)][0]
        else:
            target = matches[0][0]
        self.move(target - self.index)

    def remember_reviewer(self, *args):
        self.settings.setValue("reviewer_name", self.reviewer.text().strip())

    def own_blind_review(self, sample):
        # One reviewer per PC: any independent decision on the current result is theirs.
        return bool(
            sample["review_state"]
            and sample["review_current"]
            and sample["review_origin"] == BLIND_ORIGIN
        )

    def show_progress(self, sample):
        state = STATES.get(sample["review_state"], "미검수")
        self.progress.setText(f"{self.index + 1} / {len(self.items)} · {state}")

    def position_key(self):
        return f"review/{self.project.project_id}/{self.run_id}/{self.filter.currentData()}"

    def blind_key(self):
        return f"review/{self.project.project_id}/blind"

    def toggle_blind(self, enabled):
        # Unsaved edits were made under the other mode; saving them now would
        # misrecord their provenance.
        if self.pending_save or self.dirty or (self.task and self.task.isRunning()):
            self.blind.blockSignals(True)
            self.blind.setChecked(not enabled)
            self.blind.blockSignals(False)
            self.status.setText("수정 중인 항목을 저장한 뒤 독립 판정 모드를 바꾸세요.")
            return
        if self.project:
            self.settings.setValue(self.blind_key(), enabled)
        self.update_summary()
        self.load_current()

    def remember_position(self):
        if self.project and self.run_id and self.items:
            self.settings.setValue(self.position_key(), self.items[self.index]["id"])

    def bind(self, project, run_id):
        if self.task and self.task.isRunning():
            return False
        if not self.flush():
            return False
        self.remember_position()
        self.image_cache.clear()
        self.cache_bytes = 0
        self.project = project
        self.run_id = run_id
        self.items = []
        self.index = 0
        self.blind.blockSignals(True)
        self.blind.setChecked(
            bool(project) and self.settings.value(self.blind_key(), False, type=bool)
        )
        self.blind.blockSignals(False)
        if project and run_id:
            self.reload()
        else:
            self.load_current()
        return True

    def flush(self, on_saved=None):
        if self.pending_save:
            return False
        if self.dirty:
            if on_saved:
                self.save("DRAFT", asynchronous=True, on_saved=on_saved)
                return False
            return self.save("DRAFT")
        return True

    def reload(self, *args):
        if not self.project or not self.run_id or not self.flush(on_saved=self.reload):
            return
        if self.task and self.task.isRunning():
            return
        self.items = review_queue(self.project, self.run_id, self.filter.currentData())
        saved_id = self.settings.value(self.position_key(), "")
        self.index = next(
            (i for i, sample in enumerate(self.items) if sample["id"] == saved_id),
            min(self.index, max(0, len(self.items) - 1)),
        )
        self.update_summary()
        self.load_current()

    def update_summary(self):
        counts = (
            review_summary(self.project, self.run_id)
            if self.project and self.run_id
            else dict.fromkeys(
                ("total", "required_remaining", "completed", "deferred", "blind_completed"), 0
            )
        )
        text = f"전체 {counts['total']:,} · 필수 검수 남음 {counts['required_remaining']:,} · 완료 {counts['completed']:,} · 보류 {counts['deferred']:,}"
        if self.blind.isChecked() or counts["blind_completed"]:
            text += f" · 독립 판정 완료 {counts['blind_completed']:,}"
        self.summary.setText(text)

    def apply_labels(self, source):
        if not self.items or self.loaded_sample_id != self.items[self.index]["id"]:
            return
        if source != "manual" and self.blind.isChecked():
            return
        if source == "manual":
            self.labels.setFocus()
            self.decision_hint.setText("최종 열에서 라벨을 수정하고 근거를 기록하세요.")
            self.notes.toggle.setChecked(True)
            return
        sample = self.items[self.index]
        doc, _ = strict_json(sample["original_raw"])
        if source == "ai":
            if not sample["prediction"]:
                return
            prediction = json.loads(sample["prediction"])
            labels, reason, english = prediction["labels"], prediction["reason"], ""
        else:
            labels = json.loads(sample["original_labels"])
            reason, english = doc.get("reason_ko", ""), doc.get("reason", "")
            if any("fixed" in field and labels[field["key"]] != field["fixed"] for field in FIELDS):
                reason, english = "", ""
        self.loading = True
        for field in FIELDS:
            self.set_label_value(field, labels[field["key"]])
        self.reason.setPlainText(reason if isinstance(reason, str) else "")
        self.reason_en.setText(english if isinstance(english, str) else "")
        self.loading = False
        self.changed(invalidate_english=False)
        self.decision_hint.setText(
            ("원본" if source == "original" else "AI") + " 라벨 선택 · 아직 검수 완료가 아닙니다."
        )
        self.notes.toggle.setChecked(True)

    def showEvent(self, event):
        self.last_interaction = time.monotonic()
        super().showEvent(event)

    def hideEvent(self, event):
        self.last_interaction = time.monotonic()
        super().hideEvent(event)

    def track_effort(self):
        stamp = time.monotonic()
        if self.isVisible() and not self.loading and self.loaded_sample_id:
            self.effort_seconds += min(30.0, max(0, stamp - self.last_interaction))
        self.last_interaction = stamp

    def changed(self, *args, invalidate_english=True):
        if self.loading:
            return
        # A decided label becomes a plain change/no-change toggle again.
        for box in self.boxes.values():
            if box.isTristate() and box.checkState() != Qt.CheckState.PartiallyChecked:
                box.setTristate(False)
        self.update_other_detail()
        self.track_effort()
        if invalidate_english:
            self.reason_en.blockSignals(True)
            self.reason_en.clear()
            self.reason_en.blockSignals(False)
        self.dirty = True
        self.decision_hint.setText("수정 중 · ‘저장’을 눌러 확정하세요.")
        if self.auto.isChecked():
            self.timer.start()

    def autosave(self, asynchronous=False):
        if self.dirty and self.reviewer.text().strip():
            self.save("DRAFT", asynchronous=asynchronous)

    def load_current(self):
        self.effort_seconds = 0.0
        self.last_interaction = time.monotonic()
        self.timer.stop()
        self.flash.stop()
        self.flicker.setChecked(False)
        self.loading = True
        self.panel_scroll.verticalScrollBar().setValue(0)
        self.remember_position()
        self.decision_hint.setText(
            "노란 칸(–)은 미확정입니다. 변화가 보이는 라벨만 표시하고 Ctrl+0으로 나머지를 ‘없음’으로 정하세요."
            if self.blind.isChecked()
            else "라벨 선택 후 ‘저장’으로 확정하세요."
        )
        self.loaded_sample_id = None
        self.images = None
        for view in (self.left, self.right):
            view.placeholder = (
                "이미지를 불러오는 중입니다." if self.items else "검수 항목을 선택하세요."
            )
            view.scene().clear()
            view.viewport().update()
        for button in self.buttons:
            button.setEnabled(bool(self.items))
        self.labels.setEnabled(bool(self.items))
        self.reason.setEnabled(bool(self.items))
        if not self.items:
            self.identity.setText("해당 조건의 검수 항목이 없습니다.")
            self.status.setText(
                "현재 필터의 검수 대상이 없습니다. 전체 완료 여부는 검수 요약과 최종 검증에서 확인하세요."
            )
            self.images = None
            self.left.scene().clear()
            self.right.scene().clear()
            self.ai_reason.clear()
            self.ai_details.clear()
            self.label_heading.setText("최종 라벨 확정")
            self.reason.clear()
            self.other_detail.clear()
            self.reason_en.clear()
            for box in self.boxes.values():
                box.setChecked(False)
            self.progress.setText("항목 없음")
            self.signals.hide()
            for i in range(len(FIELDS)):
                for col in (1, 2):
                    self.labels.setItem(i, col, QTableWidgetItem("—"))
                self.labels.item(i, 0).setBackground(QColor("#ffffff"))
            self.loading = False
            self.dirty = False
            self.image_task_finished()
            return
        sample = self.items[self.index]
        self.identity.setText(sample["logical_key"])
        original = json.loads(sample["original_labels"])
        prediction = json.loads(sample["prediction"]) if sample["prediction"] else None
        blind = self.blind.isChecked()
        # Blind review starts undecided; only the reviewer's own blind revisions
        # are shown, never drafts that were seeded from source or AI labels.
        own_blind = self.own_blind_review(sample)
        if blind:
            final = json.loads(sample["reviewed_labels"]) if own_blind else dict.fromkeys(original)
        else:
            final = json.loads(sample["reviewed_labels"]) if sample["reviewed_labels"] else original
        for i, f in enumerate(FIELDS):
            different = (
                not blind
                and prediction is not None
                and original[f["key"]] != prediction["labels"][f["key"]]
            )
            self.labels.item(i, 0).setBackground(QColor("#fff2d5" if different else "#ffffff"))
            for col, value in [
                (1, original[f["key"]]),
                (2, prediction["labels"][f["key"]] if prediction else None),
            ]:
                item = QTableWidgetItem(
                    "숨김"
                    if blind
                    else "변화"
                    if value
                    else "없음"
                    if value is not None
                    else "미확정"
                )
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setForeground(QColor("#126b65" if value and not blind else "#6b7b86"))
                if different:
                    item.setBackground(QColor("#fff2d5"))
                self.labels.setItem(i, col, item)
            self.set_label_value(f, final[f["key"]])
        self.label_heading.setText(
            "최종 라벨 · 독립 판정 (원본·AI 숨김)"
            if blind
            else f"최종 라벨 · AI 신뢰도 {prediction['confidence']:.0%}"
            if prediction
            else "최종 라벨 · AI 결과 없음"
        )
        original_doc, _ = strict_json(sample["original_raw"])
        if blind:
            self.reason.setPlainText(sample["reviewed_reason"] if own_blind else "")
            english = (sample["reviewed_reason_en"] if own_blind else "") or ""
        else:
            self.reason.setPlainText(
                sample["reviewed_reason"]
                if sample["review_state"]
                else original_doc.get("reason_ko", "")
            )
            # Read the effective explanation so legacy reviews cannot display stale English.
            try:
                doc = effective_doc(
                    sample["original_raw"],
                    final,
                    self.reason.toPlainText(),
                    sample["reviewed_reason_en"],
                )
                english = doc.get("reason", "")
            except ValueError:
                english = sample["reviewed_reason_en"] or ""
        self.reason_en.setText(english if isinstance(english, str) else "")
        reason_text = (
            "독립 판정 중에는 숨깁니다."
            if blind
            else prediction["reason"]
            if prediction
            else "AI 결과 없음"
        )
        self.update_other_detail()
        self.ai_reason.setText(
            "AI 근거 · " + (reason_text[:110] + "…" if len(reason_text) > 110 else reason_text)
        )
        self.ai_details.setText("" if blind else reason_text)
        self.ai_details.setToolTip("" if blind else reason_text)
        self.ai_reason.setToolTip("" if blind else reason_text)
        if blind:
            self.notes.toggle.setChecked(True)
        # Comparison signals (mismatch, source issues) would reveal hidden labels.
        flags = [] if blind else json.loads(sample["signals"])
        self.signals.setText(
            "확인할 내용 · " + "  /  ".join(SIGNALS.get(flag, flag) for flag in flags)
        )
        tone(self.signals, "warning" if flags else "info")
        self.signals.setVisible(bool(flags))
        self.status.setText("자동 저장은 초안입니다. ‘저장’을 눌러 검수를 완료하세요.")
        self.show_progress(sample)
        self.dirty = False
        self.loading = False
        self.setEnabled(False)

        try:
            cache_key = self.image_key(sample)
        except Exception:
            cache_key = (self.project.project_id, sample["id"], "unavailable")
        cached = self.image_cache.get(cache_key)
        need_diff = self.diff.isChecked()
        following = self.items[self.index + 1] if self.index + 1 < len(self.items) else None

        def load(progress):
            frames = cached or self.decode_frames(sample)
            if need_diff and len(frames) == 2:
                frames = self.with_difference(frames)
            prefetch = None
            if following:
                try:
                    key = self.image_key(following)
                    if key not in self.image_cache:
                        prefetch = (key, self.decode_frames(following))
                except Exception:
                    pass  # A failed prefetch never prevents loading the current image.
            return frames, prefetch

        if self.task:
            self.task.deleteLater()
        self.task = Task(load, self)
        self.task.done.connect(lambda result: self.receive_images(result, sample["id"], cache_key))
        self.task.failed.connect(self.images_failed)
        self.task.finished.connect(self.image_task_finished)
        self.task.start()

    def image_key(self, sample):
        from pathlib import Path

        from llm_change_tool.storage.store import one, transaction

        with transaction(self.project, readonly=True) as con:
            root = Path(one(con, "SELECT root FROM datasets")["root"])
        paths = json.loads(sample["paths"])
        stamps = []
        for image_role, relative in sorted(paths.items()):
            if image_role != "json":
                stat = safe_path(root, relative).stat()
                stamps.append((relative, stat.st_size, stat.st_mtime_ns))
        return self.project.project_id, sample["id"], str(root), tuple(stamps)

    def decode_frames(self, sample):
        return [(im.tobytes(), im.width, im.height) for im in sample_images(self.project, sample)]

    @staticmethod
    def with_difference(frames):
        from PIL import Image

        left, right = [Image.frombytes("RGB", (w, h), data) for data, w, h in frames[:2]]
        diff = ImageChops.difference(left, right)
        return list(frames[:2]) + [(diff.tobytes(), diff.width, diff.height)]

    def cache_frames(self, key, frames):
        size = sum(len(data) for data, _, _ in frames)
        if size > self.cache_limit:
            return
        previous = self.image_cache.pop(key, None)
        if previous:
            self.cache_bytes -= sum(len(data) for data, _, _ in previous)
        self.image_cache[key] = frames
        self.cache_bytes += size
        while self.cache_bytes > self.cache_limit or len(self.image_cache) > 3:
            _, removed = self.image_cache.popitem(last=False)
            self.cache_bytes -= sum(len(data) for data, _, _ in removed)

    def receive_images(self, result, sample_id, key):
        frames, prefetch = result
        self.cache_frames(key, frames)
        if prefetch:
            self.cache_frames(*prefetch)
        self.images_loaded(frames, sample_id)

    def image_task_finished(self):
        self.setEnabled(True)
        ready = bool(self.items) and self.loaded_sample_id == self.items[self.index]["id"]
        self.labels.setEnabled(ready)
        self.reason.setEnabled(ready)
        self.reason_en.setEnabled(ready)
        blind = self.blind.isChecked()
        self.original_button.setEnabled(ready and not blind)
        self.ai_button.setEnabled(
            ready and not blind and bool(self.items[self.index]["prediction"])
        )
        # Blind mode cannot use source/AI labels; that row space goes to the bulk "none".
        self.original_button.setVisible(not blind)
        self.ai_button.setVisible(not blind)
        self.rest_unchanged_button.setVisible(blind)
        self.rest_unchanged_button.setEnabled(ready)
        self.edit_button.setEnabled(ready)
        self.diff.setEnabled(ready)
        self.flicker.setEnabled(ready)
        for i, button in enumerate(self.buttons):
            button.setEnabled(bool(self.items) if i in (0, 1, 4) else ready)

    def images_failed(self, message):
        self.loaded_sample_id = None
        self.images = None
        for view in (self.left, self.right):
            view.placeholder = "이미지를 불러오지 못했습니다.\n파일과 데이터 경로를 확인하세요."
            view.scene().clear()
            view.viewport().update()
        self.status.setText(
            "이미지 오류 · 저장을 차단했습니다. 파일을 복구한 뒤 목록을 다시 불러오세요.\n"
            + explain_error(message)
        )
        tone(self.status, "error")

    def images_loaded(self, frames, sample_id):
        if not self.items or self.items[self.index]["id"] != sample_id:
            return
        self.images = [
            QImage(data, w, h, w * 3, QImage.Format.Format_RGB888).copy() for data, w, h in frames
        ]
        self.loaded_sample_id = sample_id
        tone(self.status, "info")
        self.show_images()
        self.left.fit()

    def show_images(self, *args):
        if self.images:
            self.left.display(self.images[0])
            if self.diff.isChecked() and len(self.images) == 2:
                if self.task and self.task.isRunning():
                    return
                frames = []
                for im in self.images:
                    raw, stride = bytes(im.constBits()), im.bytesPerLine()
                    packed = b"".join(
                        raw[y * stride : y * stride + im.width() * 3] for y in range(im.height())
                    )
                    frames.append((packed, im.width(), im.height()))
                sample_id = self.loaded_sample_id
                self.setEnabled(False)
                if self.task:
                    self.task.deleteLater()
                self.task = Task(lambda p: self.with_difference(frames), self)
                self.task.done.connect(lambda values: self.images_loaded(values, sample_id))
                self.task.failed.connect(self.images_failed)
                self.task.finished.connect(self.image_task_finished)
                self.task.start()
                return
            self.right.display(self.images[2 if self.diff.isChecked() else 1])

    def toggle_flicker(self, enabled):
        if enabled:
            self.flash.start()
        else:
            self.flash.stop()
            self.show_images()

    def flash_frame(self):
        if self.images:
            self.flash_index = 1 - self.flash_index
            self.right.display(self.images[self.flash_index])

    def move(self, offset):
        if self.task and self.task.isRunning():
            return
        if self.items and self.flush(on_saved=lambda: self.move(offset)):
            target = self.index + offset
            if target >= len(self.items):
                self.status.setText(
                    "현재 목록의 마지막 항목입니다. 전체 완료 여부는 검수 요약과 최종 검증에서 확인하세요."
                )
                return
            self.index = max(0, target)
            self.load_current()

    def mark_undecided_unchanged(self):
        # Only undecided labels: what the reviewer already marked as changed stays.
        if (
            not self.blind.isChecked()
            or not self.items
            or self.loaded_sample_id != self.items[self.index]["id"]
        ):
            return
        for box in self.boxes.values():
            if box.checkState() == Qt.CheckState.PartiallyChecked:
                box.setCheckState(Qt.CheckState.Unchecked)

    def set_label_value(self, field, value):
        box = self.boxes[field["key"]]
        value = field.get("fixed", value)
        box.setTristate(value is None)
        box.setCheckState(
            Qt.CheckState.PartiallyChecked
            if value is None
            else Qt.CheckState.Checked
            if value
            else Qt.CheckState.Unchecked
        )

    def update_other_detail(self):
        if not self.items:
            self.other_detail.clear()
            return
        if self.blind.isChecked():
            self.other_detail.setToolTip("")
            self.other_detail.setText("기타 설명 · 독립 판정 중에는 원본 설명을 숨깁니다.")
            return
        sample = self.items[self.index]
        if "_other_description" not in sample:
            doc, _ = strict_json(sample["original_raw"])
            detail = doc.get("artifact_detail")
            sample["_other_description"] = (
                detail.get("arti_other_detail", "") if isinstance(detail, dict) else ""
            )
        description = sample["_other_description"]
        active = self.boxes["arti_other"].isChecked()
        self.other_detail.setToolTip(str(description) if active and description else "")
        self.other_detail.setText(
            f"기타 설명 · {description}"
            if active and description
            else "기타 설명 · 없음 (기타 해제 시 이전 설명을 내보내지 않습니다.)"
        )

    def save(self, state="DONE", advance=False, *, asynchronous=False, on_saved=None):
        if (
            self.pending_save
            or not self.items
            or self.loading
            or self.loaded_sample_id != self.items[self.index]["id"]
        ):
            return False
        blind = self.blind.isChecked()
        if not self.reviewer.text().strip() or len(self.reviewer.text()) > 120:
            self.status.setText("검수자 이름을 1~120자로 입력한 뒤 다시 저장하세요.")
            self.reviewer.setFocus()
            return False
        sample = self.items[self.index]
        if state == "DONE" and any(
            box.checkState() == Qt.CheckState.PartiallyChecked for box in self.boxes.values()
        ):
            self.decision_hint.setText("미확정 라벨을 변화/없음으로 선택한 뒤 저장하세요.")
            return False
        if blind and state == "DONE" and not self.reason.toPlainText().strip():
            self.decision_hint.setText("독립 판정은 판정 근거를 입력한 뒤 저장하세요.")
            self.notes.toggle.setChecked(True)
            self.reason.setFocus()
            return False
        labels = {
            k: None if box.checkState() == Qt.CheckState.PartiallyChecked else int(box.isChecked())
            for k, box in self.boxes.items()
        }
        for f in FIELDS:
            if state == "DONE" and f.get("parent") and labels[f["key"]]:
                labels[f["parent"]] = 1
        self.track_effort()
        reason, english = self.reason.toPlainText(), self.reason_en.text()
        reviewer, effort = self.reviewer.text(), self.effort_seconds
        previous = sample["revision"]
        project, run_id = self.project, self.run_id

        def persist(progress):
            return save_review(
                project,
                run_id,
                sample["id"],
                labels,
                reason,
                reviewer,
                state,
                previous,
                reason_en=english,
                elapsed_seconds=effort,
                blind=blind,
            )

        def complete(revision):
            self.effort_seconds = 0.0
            if revision != previous:
                sample["review_origin"] = BLIND_ORIGIN if blind else "local"
            sample.update(
                revision=revision,
                reviewed_labels=json.dumps(labels),
                reviewed_reason=reason,
                reviewed_reason_en=english,
                review_state=state,
                reviewer=reviewer.strip(),
                review_current=True,
            )
            self.pending_save = False
            self.setEnabled(True)
            self.dirty = False
            self.timer.stop()
            self.loading = True
            for field in FIELDS:
                self.set_label_value(field, labels[field["key"]])
            self.loading = False
            self.status.setText(
                ("이미 저장된 내용입니다" if revision == previous else "현재 항목 저장됨")
                + f" · {STATES.get(state, state)} · 이력 #{revision}"
            )
            self.progress.setText(
                f"{self.index + 1} / {len(self.items)} · {STATES.get(state, state)}"
            )
            self.update_summary()
            if state != "DRAFT" and self.filter.currentData() != "all":
                updated = review_queue(self.project, self.run_id, self.filter.currentData())
                if not any(s["id"] == sample["id"] for s in updated):
                    self.items = updated
                    self.index = min(self.index, max(0, len(updated) - 1))
                    self.load_current()
                    return True
            if advance:
                self.move(1)
            self.remember_position()
            return True

        def failed(message):
            self.pending_save = False
            self.setEnabled(True)
            self.image_task_finished()
            self.status.setText(explain_error(message))

        if asynchronous:
            if self.task and self.task.isRunning():
                return False
            self.pending_save = True
            self.timer.stop()
            self.status.setText(
                "저장 중 · 완료 후 다음 항목으로 이동합니다." if advance else "저장 중입니다."
            )
            self.setEnabled(False)
            if self.task:
                self.task.deleteLater()
            outcome = {}
            self.task = Task(persist, self)
            self.task.done.connect(lambda value: outcome.update(value=value))
            self.task.failed.connect(lambda message: outcome.update(error=message))

            def finished():
                if "error" in outcome:
                    failed(outcome["error"])
                else:
                    try:
                        complete(outcome["value"])
                        if on_saved:
                            on_saved()
                    except Exception as exc:
                        failed(explain_error(str(exc)))

            self.task.finished.connect(finished)
            self.task.start()
            return True
        try:
            return complete(persist(None))
        except Exception as exc:
            failed(explain_error(str(exc)))
            return False

    def undo(self):
        if not self.items or (self.task and self.task.isRunning()):
            return
        try:
            if self.dirty:
                self.dirty = False
                self.timer.stop()
                self.load_current()
                return
            if self.blind.isChecked():
                # Undo can restore source-seeded labels into the hidden view.
                self.status.setText(
                    "독립 판정 모드에서는 저장 이력 되돌리기를 쓸 수 없습니다. 라벨을 직접 고쳐 다시 저장하세요."
                )
                return
            sample = self.items[self.index]
            undo_review(
                self.project,
                self.run_id,
                sample["id"],
                self.reviewer.text(),
                expected_revision=sample["revision"],
            )
            self.dirty = False
            self.reload()
        except Exception as exc:
            self.status.setText(explain_error(str(exc)))

    def history(self):
        if self.items:
            history = review_history(self.project, self.run_id, self.items[self.index]["id"])
            hidden = 0
            if self.blind.isChecked():
                # Earlier non-blind reasons may quote source or AI decisions.
                sample = self.items[self.index]
                visible = [
                    r
                    for r in history
                    if r["origin"] == BLIND_ORIGIN and r["result_hash"] == sample["result_hash"]
                ]
                hidden = len(history) - len(visible)
                history = visible
            text = "\n\n".join(
                f"r{r['revision']} · {r['state']} · {r['reviewer']} · {r['created_at']}\n{r['reason']}"
                for r in history
            )
            if hidden:
                text += (
                    "\n\n" if text else ""
                ) + f"독립 판정 전 기록이나 이전 결과의 기록 {hidden}건은 숨겼습니다."
            QMessageBox.information(self, "검수 이력", text or "검수 이력 없음")
