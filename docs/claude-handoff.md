# Claude 이어가기 · 2026-10-18

사용자는 기존 개발·내부 실험을 Claude에서 이어가기를 요청했습니다.
이번 작업은 인계 문서 준비이며 새 기능 구현이나 유료 처리 지시가 아닙니다.

## 시작 시 읽을 자료

1. [AGENTS.md](../AGENTS.md): 개발 계약과 최신 사용자 결정 전체.
2. [HANDOFF.md](../HANDOFF.md): 구현·검증 이력. 과거 미완료 목록을 현재 버그로 단정하지 말 것.
3. [내부 실험 계획](independent-experiment-plan.md): 회사 회신 없이 진행하는 범위와 순서.
4. [평가 정책](evaluation-policy.md), [평가 검증](evaluation-verification-20261015.md).
5. [검수·비용 수정 기록](handoff-fixes-20261015.md), [아키텍처](architecture.md).

> **2026-10-19 현재:** PR #11은 main에 병합됐고(`ce52d20`) v0.1.11이 배포됐습니다.
> 아래 10-18 기록의 브랜치·PR·배포 상태는 그 시점 기준입니다. 새 작업은 최신 main에서 새 브랜치로 시작하세요.

## 이번에 확인한 저장소 상태 (2026-10-18)

- 경로: `C:\Users\rlarj\orca\workspaces\LLM-change-tool\https-github.com-kosmos-s-llm-change-tool-v2`
- 브랜치: `fix/handoff-review-and-budget`.
- 인계 문서 추가 전 HEAD: `d014b45b16c508e957e4c85ec48d0430f80f2395`.
- 인계 작업 시작 시 미커밋 변경 없음. 로컬 origin 추적 참조와 차이 없음.
  원격 조회는 수행하지 않았으므로 현재 GitHub PR·CI·배포 상태는 재확인해야 함.
- 기존 문서의 PR은 #11, 마지막 배포 기록은 v0.1.10. 이 둘은 이번에 원격 검증한 정보가 아님.
- `.venv\Scripts\python.exe` 존재, Python 3.11.17 실행 확인.
- `pytest --collect-only -q`: 161개 수집 성공. 이는 전체 테스트 통과 재검증이 아님.

이번 인계에서 앱 코드·회사 원본·프로젝트 DB는 수정하지 않았습니다.
기존 161개 전체 통과 기록은 2026-10-15 검증 문서의 기록입니다.

## 중복 구현하지 않을 것

현재 코드에서 다음 구현의 존재를 확인했습니다. 고장 신고가 있으면 먼저 재현하세요.

- `core/labels.py`: arti_other 해제 시 최종 arti_other_detail 제거.
- `core/jobs.py`, `core/costs.py`: 요청별 비용 예약과 이력, 재개 설정.
- `storage/database.py`, `storage/schema_v7.py`: DB 스키마 7과 마이그레이션.
- `core/metrics.py`, `core/evaluation.py`, `scripts/evaluate_models.py`:
  scene-f1-v1 및 같은 고정 사람 정답에 대한 실제 모델 예측 비교.
- 신규 낮은 신뢰도 검수 정책과 기존 core 시험용 호환은
  `tests/test_handoff_regressions.py` 등에서 확인 가능.

UI는 `ui/`, DB는 `storage/`, 업무 로직은 `core/`, 호출은 `providers/`,
장시간 작업은 `worker.py`와 `ui/tasks.py`로 분리합니다. Core에 Qt를 넣지 마세요.
라벨 레지스트리 실제 경로는
`src/llm_change_tool/resources/label_schemas/label_schema_v1.json`입니다.

## 같은 PC에만 있는 준비 자료

다음 경로의 존재와 안내·요약 파일을 읽어 확인했습니다. 아래 상태는 기존 로컬
기록 기준이며, 이번에 DB를 열거나 원본 전체 해시를 다시 검증하지 않았습니다.
실제 검수 시작 전 현재 DB 상태를 재확인하고, 쓰기·마이그레이션 전에 백업하세요.
회사 자료·DB·표본 목록·상세 집계는 Git에 추가하지 마세요.

| 위치 | 용도와 이어갈 지점 |
| --- | --- |
| `artifacts/evaluation-pilot-20261015-a0799582/README.md` | 사용할 20건 검수 안내. `project/`가 실제 검수 대상이며 `restored/`는 복원 시험본 |
| `artifacts/independent-experiment-v1-781dd78f/README.md` | 전체 후보 점검과 내부 실험 준비 안내 |
| 위 실험 폴더의 `development-project/` | val 50건 Mock 초안 준비본. 기존 기록은 완료 0건, 초안 50건 |
| 위 실험 폴더의 `selection-v1.json` | 최종 val 50건·test 200건 목록. `selection.json`은 초기 탐색본이므로 최종 목록으로 쓰지 말 것 |
| 위 실험 폴더의 `ready-summary.json` | 준비 완료 상태 기록. 사람 정답·실제 예측·측정 성능과 구분 |
| 위 실험 폴더의 `development-human-truth-blank.csv` | val 영상 판정 메모. CSV 수정은 앱 DB에 자동 반영되지 않음 |
| 위 실험 폴더의 `holdout-human-truth-blank.csv` | 별도 test 정답 양식. 개발·프롬프트 조정에 사용 금지 |
| `local-reference/` | 로컬 입력 복사본. Git 제외. 같은 이름의 실험 폴더 참조 |

20건 프로젝트의 기존 기록은 완료 0건·초안 20건이며 Export Gate 차단입니다.
전체 후보 점검·표본 준비를 처음부터 다시 만들기 전에 위 결과의 지문·선정 기준과
현재 원본을 대조하세요. seed나 최종 목록을 임의로 바꾸지 마세요.

Git clone만으로 로컬 자료는 전달되지 않습니다. 다른 PC라면 사용자가 허용한
별도 경로로 자료·프로젝트를 전달해야 하며 Git에 넣어 전달하지 마세요.

## 2026-10-18 Claude 진행 기록

- 로컬 DB를 읽기 전용으로 재확인했습니다. 20건·50건 프로젝트 모두 DB 스키마 7, 사람 검수 완료 0,
  초안만 있음(20/50)입니다. 초안 70건 전부가 **원본 라벨을 그대로 복사한 것**(reviewer
  `offline workflow preparation`)이고, Golden Set·모델 평가는 0건입니다. 10-15 이후 변경은 없습니다.
- 원본 라벨 쪽으로 판정이 쏠리는 것을 막기 위해 이미지 검수에 「독립 판정」 모드를 추가했습니다.
  사용법은 [사용자 설명서](user-guide.md)에 있습니다.
  - `core/reviews.py`: origin `blind`, 완료 시 근거 필수, `review_queue.review_origin`, `review_summary.blind_completed`.
  - `core/metrics.py`: Golden 결과·메타데이터에 `blind_reviews` 기록(지문 불변).
  - `ui/reviewer.py`: 원본·AI 열과 근거·신호 숨김, 미확정에서 시작, 되돌리기 차단, 이력 필터, 프로젝트별 설정 기억.
  - 테스트: `tests/test_blind_review.py`. DB 마이그레이션은 추가하지 않았습니다.
- AGENTS.md에 사용자에게 보이는 오류 메시지는 한국어로 작성한다는 규칙을 추가했습니다.
- 로컬 `artifacts/` 정리: 일회성 스크립트는 `tools/`, 검증 결과·PR 초안은 `records/`,
  캐시와 이전 안내 파일은 `archive/cleanup-20261018/`로 옮겼습니다. 색인은 `artifacts/README.md`에 있습니다.
  프로젝트 DB가 데이터 폴더의 절대경로를 저장하므로 프로젝트 폴더, `local-reference/`, `dataset_sample/`은
  옮기지 않았습니다. 삭제한 파일은 없습니다.
- holdout test 200건 검수 프로젝트는 아직 만들지 않았습니다. val로 설정을 정하기 전에 test 정답 작업을 시작할지는
  사용자 일정에 따라 결정하세요. 만들 경우 독립 판정 모드를 기본으로 사용합니다.

## 2026-10-18 Codex 후속 수정

Claude의 독립 판정 구현을 점검해 다른 검수자 또는 오래된 비교 결과의 판정이
자신의 판정처럼 나타나는 두 경우를 회귀 테스트로 재현하고 수정했습니다.
현재 검수자 이름·독립 판정 출처·최신 비교 결과가 일치할 때만 기존 판정과 근거를
복원하며, 이력 창에도 같은 규칙을 적용합니다. 이름 변경 시 표시 내용을 갱신하고,
작성 중 다른 이름으로 바꾸는 것은 차단합니다. 이름 없이 판정을 시작한 경우에는
작성 후 이름 입력·저장을 허용합니다. DB 스키마·기존 이력·원본 파일 변경은 없습니다.

전체 pytest 167개 통과 후 마지막 이름 입력 보완과 새 테스트를 포함한 관련 23개
재검사 통과. Ruff·포맷·compileall·합성 6건 self-test(network_calls=0)·GUI/worker
smoke 통과. 자세한 범위와 사용자 확인은
[독립 판정 후속 검증 기록](blind-review-verification-20261018.md)을 확인하세요.

## 2026-10-19 Claude 검토 후 보완

Codex 수정분을 검토해 찾은 문제를 고쳤습니다. DB 스키마·기존 이력·원본은 바꾸지 않았습니다.

- 숨겨진 다른 검수자의 독립 판정 위에 저장하면 그 판정이 경고 없이 Golden Set에서 밀려났습니다.
  이제 저장 전에 확인 창을 띄우고, 그 항목은 자동 임시 저장을 하지 않습니다.
  한 항목에 검수자별 판정을 모두 보존해 일치율을 낼지는 아직 사용자 결정 사항입니다.
- 자동 임시 저장이 덜 친 이름("te")으로 초안을 저장하고 다음 글자에서 화면을 비우던 문제를 고쳤습니다.
  이름은 입력을 마쳤을 때(`editingFinished`) 반영합니다.
- 검수자가 바뀌면 소요 시간을 초기화합니다.
- `tests/conftest.py`의 autouse fixture와 `scripts/capture_ui.py`가 실제 레지스트리
  (`HKCU\Software\KOSMOS\LLMChangeTool`) 대신 임시 INI 설정을 씁니다. 이전 테스트가 남긴
  위치 기록 키는 그대로 있습니다(이름 기억은 꺼져 있고 저장된 이름 없음을 확인).
- 전체 pytest 171개 통과(테스트 전후 레지스트리 항목 수 동일), Ruff·포맷·compileall·비밀정보 검사,
  self-test(network_calls=0), GUI smoke 통과.
- 사용자가 10-19에 v0.1.11 릴리스를 요청했습니다. PR #11 CI(Windows/Linux, Portable 빌드)가 통과한 뒤
  main에 병합했고(`ce52d20`), `release.yml`이 EXE 검사를 마치고 Portable ZIP과 SHA256을 공개했습니다.
  https://github.com/kosmos-s/llm-change-tool-v2/releases/tag/v0.1.11
  이 요청은 이번 릴리스에만 해당합니다. 이후 main 병합·릴리스는 다시 사용자 요청이 필요합니다.

## 다음 작업 순서

1. `git status`, 브랜치·HEAD, 하위 지침을 확인합니다. 위 로컬 안내와 최종 선정본을
   읽고 실제 현재 상태를 확인합니다. 기존 점검·선정 결과를 재사용할 수 있으면 보존합니다.
2. 사용자가 20건의 T1/T2를 직접 검수할 수 있게 앱을 준비합니다.
   `run.bat --project artifacts/evaluation-pilot-20261015-a0799582/project`로 실행할 수 있습니다.
   검수자·라벨·한국어 사유 확인 → 저장 → 재실행 → 별도 JSON 내보내기 대조를 진행합니다.
   AI가 기존 라벨이나 Mock 결과를 사람 확정 정답으로 자동 승인하면 안 됩니다.
3. val 50건의 독립적인 사람 정답과 오류 사례를 준비합니다. 실제 LLM 호출은 모델·예산과
   별도 호출 지시가 필요합니다. 호출 승인 없이도 검수·시연 준비는 계속할 수 있습니다.
4. test 200건은 설정 확정 뒤 실제 예측과 고정 정답으로 평가합니다. 내부 대표 지표는
   arti/tree/fore/farm/water의 OR에 대한 F1, 보조는 주요 라벨 micro F1입니다.
   0.85는 미측정 내부 목표이며 회사 확정 목표가 아닙니다.
5. 실제 버그가 재현되면 관련 회귀 테스트와 필수 검사를 수행하고 작업 단위로 커밋합니다.
   push·PR 요청이 있으면 검증한 브랜치로 진행하되 main 병합·새 릴리스는 별도 요청이 필요합니다.

회사 답변 부재는 내부 개발·점검·검수의 차단 조건이 아닙니다. 회사 모델 학습 코드·가중치·환경은
기존 조사에서 확보되지 않았습니다. Mock 점수나 라벨 비교를 실제 재학습 향상으로 보고하지 마세요.

## 검증 명령

저장소 루트의 PowerShell에서 실행합니다. 기존 환경을 먼저 사용하고 재설치를 서두르지 마세요.

```powershell
.venv\Scripts\python.exe scripts/check_secrets.py
.venv\Scripts\python.exe -m compileall -q src
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m ruff format --check .
$env:QT_QPA_PLATFORM = 'offscreen'
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m llm_change_tool --self-test
.venv\Scripts\python.exe -m llm_change_tool --gui-smoke
```

비밀정보 검사는 Git index를 검사하므로 커밋 대상 문서를 stage한 뒤 다시 확인합니다.
앱 코드 변경 시 관련 테스트를 먼저 실행하고 CI 필수 검사를 마무리하세요.
데이터 흐름 변경 시 합성/Mock의 Import → 검수 → 저장 → 재실행 → 내보내기와 원본 보존을 확인합니다.
문서 인계만으로 실제 PC 실사용·사람 검수·모델 정확도가 검증되는 것은 아닙니다.

## Claude에 붙여넣을 시작 프롬프트

```text
이 저장소의 작업을 이어받아 줘. CLAUDE.md → AGENTS.md → HANDOFF.md →
docs/claude-handoff.md를 읽고 현재 Git·코드·로컬 준비 상태를 먼저 확인해.
이미 수정된 검수·비용·평가 기능이나 완료된 전체 후보 점검·표본 선정을 중복하지 마.
기존 20건 검수 프로젝트와 val 50건 개발 준비본을 기준으로 내부 실험 계획의 다음
필요 작업을 진행해. 사람 정답은 자동으로 만들지 말고 실제 사람 검수를 지원해.
회사 회신 없이 가능한 개발·오프라인 준비는 계속해. 원본·검수 이력을 보존하고,
유료 API·회사 서버·본처리·main 병합·릴리스는 별도 지시 없이 진행하지 마.
변경 사항, 검증 근거, 사용자 PC 확인, 회사 미확정 사항은 나눠서 한국어로 설명해.
```
