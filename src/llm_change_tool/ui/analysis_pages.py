"""Team exchange, conflicts and model evaluation views."""

import json
from pathlib import Path
from uuid import uuid4

from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from llm_change_tool.core.exchange import (
    conflicts,
    export_reviews,
    import_reviews,
    resolve_conflict,
)
from llm_change_tool.core.metrics import (
    create_golden,
    dashboard,
    evaluate_golden,
    export_golden_template,
    export_review_report,
    import_model_predictions,
    model_comparison,
    review_report,
)
from llm_change_tool.core.projects import restore_project
from llm_change_tool.storage.store import rows, transaction
from llm_change_tool.ui.components import DashboardPanel, ResultPanel, card, scroll_page, text_label


def add_pages(window):
    team = QWidget()
    layout = QVBoxLayout(team)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(18)
    frame, content = card(
        "검수 결과 주고받기",
        "같은 데이터 · 작업 계획 · AI 결과를 사용하는 팀원과 검수 ZIP을 교환합니다.",
    )
    bar = QHBoxLayout()
    window.button(
        "검수 ZIP 내보내기",
        lambda: window.background(lambda p: export_reviews(window.project, window.run_id)),
        bar,
        primary=True,
        requires="run",
    )
    window.button("검수 ZIP 가져오기", lambda: choose_zip(window), bar, requires="run")
    window.button("충돌 확인 · 해결", lambda: resolve_next(window), bar, requires="run")
    bar.addStretch()
    content.addLayout(bar)
    content.addWidget(
        text_label(
            "새 결과는 반영하고, 동일한 결과는 유지합니다. 서로 다른 결정은 충돌로 표시하며 직접 선택해야 반영됩니다.",
            "muted",
        )
    )
    layout.addWidget(frame)
    frame, content = card(
        "백업에서 작업 이어가기",
        "팀원에게 받은 DB 백업이나 내 백업을 새 프로젝트 폴더로 복원합니다.",
    )
    bar = QHBoxLayout()
    window.button("DB 백업 복원", lambda: restore(window), bar, requires=None)
    bar.addWidget(text_label("기존 프로젝트를 덮어쓰지 않습니다.", "muted"), 1)
    content.addLayout(bar)
    content.addWidget(
        text_label(
            "복원 후 ‘데이터 · AI 분석’에서 같은 데이터 폴더를 다시 선택하면 현재 PC의 경로로 연결됩니다. 검수 ZIP에는 이미지와 API Key가 포함되지 않습니다.",
            "muted",
        )
    )
    layout.addWidget(frame)
    window.team_result = ResultPanel("검수 ZIP 교환과 복원 결과가 여기에 표시됩니다.")
    layout.addWidget(window.team_result)
    layout.addStretch()
    window.tabs.addTab(scroll_page(team), "팀 작업 · 복원")
    stats = QWidget()
    layout = QVBoxLayout(stats)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(18)
    bar = QHBoxLayout()
    bar.addWidget(text_label("선택한 작업의 진행 현황", "sectionTitle"), 1)
    window.button(
        "현황 새로고침",
        lambda: window.background(lambda p: dashboard(window.project, window.run_id)),
        bar,
        primary=True,
    )
    layout.addLayout(bar)
    window.analysis = DashboardPanel()
    layout.addWidget(window.analysis)
    bar = QHBoxLayout()
    window.button(
        "수정률 · 검수 시간",
        lambda: window.background(lambda p: review_report(window.project, window.run_id)),
        bar,
        requires="run",
    )
    window.button(
        "검수 보고서 저장",
        lambda: window.background(lambda p: export_review_report(window.project, window.run_id)),
        bar,
        requires="run",
    )
    window.button("자동 유지 표본 검수", lambda: auto_audit(window), bar, requires="run")
    layout.addLayout(bar)
    frame, content = card(
        "기준 데이터 · AI 평가",
        "사람이 확정한 검수를 Golden Set으로 고정하고, 프롬프트와 모델별 결과를 비교합니다.",
    )
    bar = QHBoxLayout()
    window.button("확정 검수를 기준으로 고정", lambda: new_golden(window), bar, requires="run")
    window.button("AI 작업별 평가 비교", lambda: golden_action(window, "evaluate"), bar)
    bar.addStretch()
    content.addLayout(bar)
    layout.addWidget(frame)
    frame, content = card(
        "변화탐지 모델 평가",
        "Baseline과 재학습 모델의 예측 파일을 각각 가져와 Precision · Recall · F1 · F2를 비교합니다.",
    )
    bar = QHBoxLayout()
    window.button("1  예측 양식 받기", lambda: golden_action(window, "template"), bar)
    window.button("2  모델 예측 가져오기", lambda: model_import(window), bar)
    window.button(
        "3  평가 결과 비교",
        lambda: window.background(lambda p: model_comparison(window.project)),
        bar,
    )
    content.addLayout(bar)
    layout.addWidget(frame)
    window.tabs.addTab(scroll_page(stats), "통계 · 평가")


def display(window, value):
    window.analysis.set_result(value)


def choose_zip(window):
    path, _ = QFileDialog.getOpenFileName(window, "검수 패키지", "", "ZIP (*.zip)")
    if path:
        window.background(lambda p: import_reviews(window.project, window.run_id, Path(path)))


def resolve_next(window):
    if not window.project or not window.run_id:
        return
    values = conflicts(window.project, window.run_id)
    if not values:
        return QMessageBox.information(window, "충돌", "미해결 충돌이 없습니다.")
    conflict = values[0]
    incoming = json.loads(conflict["payload"])
    current = conflict["current"]
    from llm_change_tool.core.labels import FIELDS

    def selected(labels):
        if isinstance(labels, str):
            labels = json.loads(labels)
        return (
            ", ".join(field["title"] for field in FIELDS if labels.get(field["key"]))
            or "모든 라벨 변화 없음"
        )

    dialog = QMessageBox(window)
    dialog.setWindowTitle(f"충돌 해결 · 남은 {len(values)}건")
    dialog.setText(
        f"샘플 {conflict['sample_id']}\n\n내 결과 ({current['reviewer']})\n{selected(current['labels'])}\n{current['reason']}\n\n가져온 결과 ({incoming['reviewer']})\n{selected(incoming['labels'])}\n{incoming['reason']}"
    )
    local = dialog.addButton("내 결과 유지", QMessageBox.ButtonRole.AcceptRole)
    remote = dialog.addButton("가져온 결과 사용", QMessageBox.ButtonRole.DestructiveRole)
    dialog.addButton("나중에", QMessageBox.ButtonRole.RejectRole)
    dialog.exec()
    if dialog.clickedButton() in (local, remote):
        choice = "local" if dialog.clickedButton() == local else "incoming"
        window.background(
            lambda p: resolve_conflict(window.project, conflict["id"], choice, current["revision"])
        )


def restore(window):
    path, _ = QFileDialog.getOpenFileName(window, "DB 백업 선택", "", "SQLite (*.db *.sqlite3)")
    if not path:
        return
    parent = QFileDialog.getExistingDirectory(window, "복원할 새 프로젝트의 부모 폴더")
    if parent:
        window.perform_project_operation(
            lambda: restore_project(Path(path), Path(parent) / f"restored-{uuid4().hex[:10]}"),
            window.set_project,
        )


def auto_audit(window):
    from llm_change_tool.core.reviews import select_auto_audit

    count, ok = QInputDialog.getInt(window, "자동 유지 표본 검수", "검수할 개수", 30, 1, 3000)
    if not ok:
        return
    seed, ok = QInputDialog.getText(
        window, "표본 seed", "같은 seed는 같은 표본 순서를 만듭니다.", text="20260324"
    )
    if ok:
        window.background(lambda p: select_auto_audit(window.project, window.run_id, count, seed))


def new_golden(window):
    name, ok = QInputDialog.getText(window, "Golden Dataset", "Reference set 이름")
    if not ok:
        return
    title, ok = QInputDialog.getItem(
        window, "사용 목적", "목적", ["평가용", "학습용", "탐색용"], 0, False
    )
    if not ok:
        return
    purpose = {"평가용": "evaluation", "학습용": "training", "탐색용": "exploration"}[title]
    choices = {
        "evaluation": ["test", "val"],
        "training": ["train"],
        "exploration": ["train", "val", "test"],
    }[purpose]
    split, ok = QInputDialog.getItem(window, "데이터 분리", "split", choices, 0, False)
    if ok:
        window.background(
            lambda p: create_golden(
                window.project, window.run_id, name, purpose=purpose, split=split
            ),
            lambda v: display(window, v),
        )


def golden_action(window, action):
    if not window.project:
        return
    with transaction(window.project) as con:
        sets = rows(
            con,
            "SELECT g.*,m.purpose,m.split FROM golden_sets g LEFT JOIN golden_metadata m ON m.set_id=g.id ORDER BY g.created_at",
        )
    if not sets:
        return window._error(ValueError("먼저 Golden Set을 고정하세요."))
    names = [
        f"{s['name']} · {s['purpose'] or '기존/목적 미지정'} / {s['split'] or '미지정'} · {s['id']}"
        for s in sets
    ]
    selected, ok = QInputDialog.getItem(window, "Golden Set", "선택", names, 0, False)
    if ok:
        gid = sets[names.index(selected)]["id"]
        fn = evaluate_golden if action == "evaluate" else export_golden_template
        window.background(lambda p: fn(window.project, gid), lambda v: display(window, v))


def model_import(window):
    path, _ = QFileDialog.getOpenFileName(window, "실제 모델 예측 JSON", "", "JSON (*.json)")
    if not path:
        return
    name, ok = QInputDialog.getText(window, "모델 구분", "Baseline 또는 Retrained 모델 이름")
    if ok:
        window.background(
            lambda p: import_model_predictions(window.project, Path(path), name),
            lambda v: display(window, v),
        )
