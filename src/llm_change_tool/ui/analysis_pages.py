"""Backup restore, statistics and model evaluation views."""

from pathlib import Path
from uuid import uuid4

from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QVBoxLayout,
    QWidget,
)

from llm_change_tool.core.evaluation import (
    export_comparison_report,
    load_model_evaluation,
    verify_manual_counts,
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
    # Personal use: team ZIP exchange stays in core but is not offered on screen.
    frame, content = card(
        "백업에서 작업 이어가기",
        "내 DB 백업을 새 프로젝트 폴더로 복원합니다. PC를 옮길 때도 사용합니다.",
    )
    bar = QHBoxLayout()
    window.button("DB 백업 복원", lambda: restore(window), bar, requires=None)
    bar.addWidget(text_label("기존 프로젝트를 덮어쓰지 않습니다.", "muted"), 1)
    content.addLayout(bar)
    content.addWidget(
        text_label(
            "복원 후 ‘데이터 · AI 분석’에서 같은 데이터 폴더를 다시 선택하면 현재 PC의 경로로 연결됩니다. 백업에는 이미지와 API Key가 포함되지 않습니다.",
            "muted",
        )
    )
    layout.addWidget(frame)
    window.team_result = ResultPanel("복원 결과가 여기에 표시됩니다.")
    layout.addWidget(window.team_result)
    layout.addStretch()
    window.tabs.addTab(scroll_page(team), "백업 · 복원")
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
        "내부 대표 지표는 변화 유무 F1입니다. 같은 고정 정답의 실제 예측을 비교하고 오류 사례를 사람이 확인합니다. 재학습 실행은 외부 코드에서 수행합니다.",
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
    bar = QHBoxLayout()
    window.button("4  전후 비교 · 보고서 저장", lambda: paired_comparison(window), bar)
    window.button("5  수동 집계 대조", lambda: manual_count_check(window), bar)
    content.addLayout(bar)
    layout.addWidget(frame)
    window.tabs.addTab(scroll_page(stats), "통계 · 평가")


def display(window, value):
    window.analysis.set_result(value)


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
    with transaction(window.project, readonly=True) as con:
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


def _choose_evaluation(window, title, exclude=None):
    if not window.project:
        return None
    with transaction(window.project, readonly=True) as con:
        evaluations = rows(
            con,
            "SELECT e.id,e.name,g.name golden_name FROM model_evaluations e JOIN golden_sets g ON g.id=e.golden_id ORDER BY e.created_at,e.id",
        )
    evaluations = [e for e in evaluations if e["id"] != exclude]
    if not evaluations:
        window._error(ValueError("먼저 같은 고정 정답에 대한 실제 모델 예측을 가져오세요."))
        return None
    choices = [f"{e['name']} · {e['golden_name']} · {e['id']}" for e in evaluations]
    selected, ok = QInputDialog.getItem(window, title, "평가 결과", choices, 0, False)
    return evaluations[choices.index(selected)]["id"] if ok else None


def paired_comparison(window):
    baseline = _choose_evaluation(window, "기존 모델 선택")
    if not baseline:
        return
    candidate = _choose_evaluation(window, "재학습 모델 선택", exclude=baseline)
    if candidate:
        window.background(
            lambda p: export_comparison_report(window.project, baseline, candidate),
            lambda v: display(window, v),
        )


def manual_count_check(window):
    evaluation_id = _choose_evaluation(window, "수동 집계를 대조할 모델")
    if not evaluation_id:
        return
    text, ok = QInputDialog.getText(
        window, "수동 집계 대조", "CSV와 영상을 확인한 TP,FP,FN,TN을 쉼표로 입력하세요."
    )
    if not ok:
        return
    try:
        values = [int(value.strip()) for value in text.split(",")]
        if len(values) != 4:
            raise ValueError("TP,FP,FN,TN 네 개의 정수를 입력하세요.")
        counts = dict(zip(("tp", "fp", "fn", "tn"), values, strict=True))
    except ValueError:
        window._error(ValueError("TP,FP,FN,TN 네 개의 0 이상 정수를 입력하세요."))
        return
    window.background(
        lambda p: {
            "kind": "manual_count_check",
            **verify_manual_counts(load_model_evaluation(window.project, evaluation_id), counts),
        },
        lambda v: display(window, v),
    )
