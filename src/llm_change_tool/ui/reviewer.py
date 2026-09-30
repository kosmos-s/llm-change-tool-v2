import json
import time

from PIL import ImageChops
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QImage, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
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

from llm_change_tool.core.datasets import sample_images
from llm_change_tool.core.labels import FIELDS, effective_doc, strict_json
from llm_change_tool.core.reviews import (
    review_history,
    review_queue,
    review_summary,
    save_review,
    undo_review,
)
from llm_change_tool.ui.components import STATES, Foldout, card, role, scroll_page, text_label, tone
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
    "pending": "분석 대기",
}


class ReviewWidget(QWidget):
    def __init__(self):
        super().__init__()
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
        top.addWidget(self.reviewer)
        self.auto = QCheckBox("자동 임시 저장")
        self.auto.setToolTip(
            "입력 후 잠시 멈추면 초안을 저장합니다. 완료 처리는 ‘저장’을 눌러 주세요."
        )
        self.auto.setChecked(True)
        top.addWidget(self.auto)
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
        viewer, vl = card("시점 비교", "휠로 확대 · 드래그로 이동 · 두 이미지가 함께 움직입니다.")
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
        controls.addStretch()
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
            ("보류", lambda: self.save("DEFERRED", True), "나중에 다시 검수합니다."),
            ("되돌리기", self.undo, "Ctrl+Z · 이전 검수 기록으로 복원"),
            ("이력", self.history, "검수자와 수정 기록 확인"),
            ("저장", lambda: self.save(), "Ctrl+S · 검수 완료"),
            ("저장 후 다음  →", lambda: self.save("DONE", True), "Ctrl+Enter"),
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
        self.timer.timeout.connect(self.autosave)
        self.flash = QTimer(self)
        self.flash.setInterval(500)
        self.flash.timeout.connect(self.flash_frame)
        self.flash_index = 0
        for key, fn in [
            ("Ctrl+S", lambda: self.save()),
            ("Ctrl+Return", lambda: self.save("DONE", True)),
            ("Alt+Left", lambda: self.move(-1)),
            ("Alt+Right", lambda: self.move(1)),
            ("Ctrl+Z", self.undo),
            ("F", self.left.fit),
        ]:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(fn)
        self.load_current()

    def bind(self, project, run_id):
        if self.task and self.task.isRunning():
            return False
        if not self.flush():
            return False
        self.project = project
        self.run_id = run_id
        self.items = []
        self.index = 0
        if project and run_id:
            self.reload()
        else:
            self.load_current()
        return True

    def flush(self):
        if self.dirty:
            return self.save("DRAFT")
        return True

    def reload(self, *args):
        if not self.project or not self.run_id or not self.flush():
            return
        if self.task and self.task.isRunning():
            return
        self.items = review_queue(self.project, self.run_id, self.filter.currentData())
        self.index = min(self.index, max(0, len(self.items) - 1))
        self.load_current()

    def update_summary(self):
        counts = (
            review_summary(self.project, self.run_id)
            if self.project and self.run_id
            else dict.fromkeys(("total", "required_remaining", "completed", "deferred"), 0)
        )
        self.summary.setText(
            f"전체 {counts['total']:,} · 필수 검수 남음 {counts['required_remaining']:,} · 완료 {counts['completed']:,} · 보류 {counts['deferred']:,}"
        )

    def apply_labels(self, source):
        if not self.items or self.loaded_sample_id != self.items[self.index]["id"]:
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
        self.track_effort()
        if invalidate_english:
            self.reason_en.blockSignals(True)
            self.reason_en.clear()
            self.reason_en.blockSignals(False)
        self.dirty = True
        self.decision_hint.setText("수정 중 · ‘저장’을 눌러 확정하세요.")
        if self.auto.isChecked():
            self.timer.start()

    def autosave(self):
        if self.dirty and self.reviewer.text().strip():
            self.save("DRAFT")

    def load_current(self):
        self.effort_seconds = 0.0
        self.last_interaction = time.monotonic()
        self.timer.stop()
        self.flash.stop()
        self.flicker.setChecked(False)
        self.loading = True
        self.panel_scroll.verticalScrollBar().setValue(0)
        self.update_summary()
        self.decision_hint.setText("라벨 선택 후 ‘저장’으로 확정하세요.")
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
            self.images = None
            self.left.scene().clear()
            self.right.scene().clear()
            self.ai_reason.clear()
            self.ai_details.clear()
            self.label_heading.setText("최종 라벨 확정")
            self.reason.clear()
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
        self.progress.setText(
            f"{self.index + 1} / {len(self.items)} · {STATES.get(sample['review_state'], '미검수')}"
        )
        original = json.loads(sample["original_labels"])
        prediction = json.loads(sample["prediction"]) if sample["prediction"] else None
        final = json.loads(sample["reviewed_labels"]) if sample["reviewed_labels"] else original
        for i, f in enumerate(FIELDS):
            different = (
                prediction is not None and original[f["key"]] != prediction["labels"][f["key"]]
            )
            self.labels.item(i, 0).setBackground(QColor("#fff2d5" if different else "#ffffff"))
            for col, value in [
                (1, original[f["key"]]),
                (2, prediction["labels"][f["key"]] if prediction else None),
            ]:
                item = QTableWidgetItem(
                    "변화" if value else "없음" if value is not None else "미확정"
                )
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setForeground(QColor("#126b65" if value else "#6b7b86"))
                if different:
                    item.setBackground(QColor("#fff2d5"))
                self.labels.setItem(i, col, item)
            self.set_label_value(f, final[f["key"]])
        self.label_heading.setText(
            f"최종 라벨 · AI 신뢰도 {prediction['confidence']:.0%}"
            if prediction
            else "최종 라벨 · AI 결과 없음"
        )
        original_doc, _ = strict_json(sample["original_raw"])
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
        reason_text = prediction["reason"] if prediction else "AI 결과 없음"
        self.ai_reason.setText(
            "AI 근거 · " + (reason_text[:110] + "…" if len(reason_text) > 110 else reason_text)
        )
        self.ai_details.setText(reason_text)
        self.ai_details.setToolTip(reason_text)
        self.ai_reason.setToolTip(prediction["reason"] if prediction else "AI 결과 없음")
        flags = json.loads(sample["signals"])
        self.signals.setText(
            "확인할 내용 · " + "  /  ".join(SIGNALS.get(flag, flag) for flag in flags)
        )
        tone(self.signals, "warning" if flags else "info")
        self.signals.setVisible(bool(flags))
        self.status.setText("자동 저장은 초안입니다. ‘저장’을 눌러 검수를 완료하세요.")
        self.dirty = False
        self.loading = False
        self.setEnabled(False)

        def load(progress):
            left, right = sample_images(self.project, sample)
            diff = ImageChops.difference(left, right)
            return [(im.tobytes(), im.width, im.height) for im in (left, right, diff)]

        if self.task:
            self.task.deleteLater()
        self.task = Task(load, self)
        self.task.done.connect(lambda frames: self.images_loaded(frames, sample["id"]))
        self.task.failed.connect(self.images_failed)
        self.task.finished.connect(self.image_task_finished)
        self.task.start()

    def image_task_finished(self):
        self.setEnabled(True)
        ready = bool(self.items) and self.loaded_sample_id == self.items[self.index]["id"]
        self.labels.setEnabled(ready)
        self.reason.setEnabled(ready)
        self.reason_en.setEnabled(ready)
        self.original_button.setEnabled(ready)
        self.ai_button.setEnabled(ready and bool(self.items[self.index]["prediction"]))
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
            + message
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
        if self.items and self.flush():
            self.index = max(0, min(len(self.items) - 1, self.index + offset))
            self.load_current()

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

    def save(self, state="DONE", advance=False):
        if not self.items or self.loading or self.loaded_sample_id != self.items[self.index]["id"]:
            return False
        sample = self.items[self.index]
        if state == "DONE" and any(
            box.checkState() == Qt.CheckState.PartiallyChecked for box in self.boxes.values()
        ):
            self.decision_hint.setText("미확정 라벨을 변화/없음으로 선택한 뒤 저장하세요.")
            return False
        labels = {
            k: None if box.checkState() == Qt.CheckState.PartiallyChecked else int(box.isChecked())
            for k, box in self.boxes.items()
        }
        for f in FIELDS:
            if state == "DONE" and f.get("parent") and labels[f["key"]]:
                labels[f["parent"]] = 1
        self.track_effort()
        try:
            revision = save_review(
                self.project,
                self.run_id,
                sample["id"],
                labels,
                self.reason.toPlainText(),
                self.reviewer.text(),
                state,
                sample["revision"],
                reason_en=self.reason_en.text(),
                elapsed_seconds=self.effort_seconds,
            )
            self.effort_seconds = 0.0
            sample.update(
                revision=revision,
                reviewed_labels=json.dumps(labels),
                reviewed_reason=self.reason.toPlainText(),
                reviewed_reason_en=self.reason_en.text(),
                review_state=state,
            )
            self.dirty = False
            self.timer.stop()
            self.loading = True
            for field in FIELDS:
                self.set_label_value(field, labels[field["key"]])
            self.loading = False
            self.status.setText(f"{STATES.get(state, state)} · 이력 #{revision}")
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
            return True
        except Exception as exc:
            self.status.setText(str(exc))
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
            self.status.setText(str(exc))

    def history(self):
        if self.items:
            history = review_history(self.project, self.run_id, self.items[self.index]["id"])
            QMessageBox.information(
                self,
                "검수 이력",
                "\n\n".join(
                    f"r{r['revision']} · {r['state']} · {r['reviewer']} · {r['created_at']}\n{r['reason']}"
                    for r in history
                )
                or "검수 이력 없음",
            )
