# 아키텍처

## 계층과 의존성

- `ui/`: PySide6 프로젝트·작업·이미지 검수·팀·평가 탭. 화면 갱신은 메인 스레드에서만 수행합니다.
- `core/`: Import, 계획, 실행, 비교, 검수, Gate, Export, ZIP, 평가. Qt 의존성 없음.
- `storage/`: SQLAlchemy Core unit of work, SQLite 버전 migration, 짧은 연결, foreign keys/WAL/busy timeout.
- `providers/`: Provider protocol, MockProvider, OpenAIProvider. Gemini/Local VLM은 같은 protocol로 추가 가능.
- `worker.py`: 별도 프로세스 DB 점검. 앱 내부 대량 작업은 `ui/tasks.py` QThread에서 같은 Core를 실행합니다.
- `resources/`: 라벨 스키마와 versioned prompt. 배포 패키지에 함께 포함합니다.

프로젝트 생성/열기/백업/복원 및 긴 Import/AI/Compare/Gate/Export/ZIP/평가 작업은 UI 스레드 밖에서 실행합니다. Job의 실제 상태는 메모리나 CSV가 아닌 SQLite에 보존됩니다. 프로젝트별 OS 파일 잠금으로 동시에 두 AI worker가 처리하지 못하게 합니다. process가 죽으면 OS가 잠금을 반환하고 recovery가 진행 중 항목을 실패/불명확으로 기록합니다.

## DB 구조 (schema v2)

| 테이블 | 역할 / 관계 |
|---|---|
| project, schema_migrations | UUID·이름·생성시각·앱 버전, 적용된 migration 기록 |
| datasets | 현재 PC의 root, portable fingerprint, 품질 오류 |
| samples | logical key, source/split/error type, 상대경로, SHA256, 원본 JSON 바이트·정규화 라벨 |
| work_plans, work_plan_items | dataset fingerprint와 정확한 sample ID 목록 고정 |
| llm_runs | plan, model/config, prompt 본문 및 SHA256, label schema SHA256 |
| jobs, job_items | Run별 실행 상태, 샘플별 상태·시도 수·오류 |
| attempts | 모든 API 시도, 예상액 예약, 토큰·추정 실제액, 불명확 응답 추적 |
| llm_results | Run/sample별 고유 성공 결과와 raw 응답 |
| comparisons | 원본·AI hash binding, 신호, 검수 필요 여부, AUTO_KEEP/REVIEW 결정 |
| reviews | append-only revision, reviewer, 원본/AI binding, 이전 revision, 상태·근거·라벨 |
| snapshots | Export manifest와 Run 관계 |
| exchange_packages, merge_conflicts | 수신 package 중복 차단, 충돌 상태·incoming·local revision |
| golden_sets, golden_items | 사람이 확정한 라벨 reference snapshot |
| model_evaluations | Golden 기준 외부 모델의 별도 평가 결과 |

이미지를 BLOB으로 저장하지 않습니다. JSON 바이트만 DB에 보존합니다. source 파일 이름/relative path와 dataset root를 조합하여 파일을 찾습니다. 같은 데이터와 계획이면 PC별 절대경로가 달라도 fingerprint가 같습니다.

Migration 1은 프로젝트 기반, migration 2는 데이터와 업무 테이블입니다. 기존 DB를 열 때 application ID와 migration 기록/버전을 검사합니다. 업그레이드 전에 Backup API로 백업하고 SQL DDL을 transaction으로 적용합니다. 지원하지 않는 미래 버전은 수정하지 않습니다. 이후 변경은 기존 migration을 고치지 않고 새 버전으로 추가합니다.

## 실행과 비용

`PENDING → RUNNING → COMPLETED/FAILED/PAUSED/CANCELLED` 상태를 사용합니다. 성공 항목은 재개 시 다시 호출하지 않습니다. 동일 plan+config+prompt+schema로 Job을 중복 생성하면 기존 Job을 돌려줍니다.

OpenAI SDK 자체 retry는 끄고 각 시도를 DB에 기록합니다. 연결/429/5xx는 제한된 exponential backoff를 사용합니다. timeout/crash로 청구 결과를 알 수 없는 경우 예약액을 남깁니다. 재시도 시 추가 비용 가능성이 있습니다. 단가·예산·입출력 토큰 예상 범위는 Run 설정에 고정합니다. 실제 비용이 예약액을 초과하면 추가 처리를 일시정지합니다.

## 판단과 최종 품질

원본, AI, 사람 검수는 별도로 보존합니다. Compare는 change/detail mismatch, confidence, self-review, malformed/API error를 기록합니다. 새 작업의 기본은 detailed이며 low confidence 단독도 필수 검수합니다. 이전 core 시험용 작업은 기존 정책을 유지하지만 production은 core를 포함해 필수 검수합니다. 이전 비교 행을 다시 쓰기 전에도 검수 목록·요약·통계·준비·Gate에 이 최소 규칙을 적용합니다.

Review는 DONE/DEFERRED/DRAFT입니다. 자동 저장은 DRAFT이며 완료를 의미하지 않습니다. Save는 새 revision을 추가하고 낙관적 잠금으로 stale overwrite를 막습니다. Undo도 기존 이력을 삭제하지 않고 새 revision을 남깁니다.

Final Gate는 plan·config·source SHA256, AI 성공/오류, Compare 및 review-list 누락, 필수 검수, deferred/draft, 유효 JSON, 팀 충돌을 검사합니다. 검수 불필요 항목만 AUTO_KEEP 원본 fallback이 허용됩니다. 필수 검수를 원본 fallback으로 숨기지 않습니다.

Gate의 human_complete/total 및 all_human_reviewed는 사람 검수 범위를 구분합니다. Gate 통과는 전건 검수나 성능 향상을 입증하지 않습니다. 최종 JSON의 arti_other가 0이면 기존 arti_other_detail 키는 빈 문자열로 정리하며 원본 바이트는 보존합니다.

Export는 원본과 분리된 `.incomplete-UUID` 준비 폴더에 JSON/JPG/manifest를 모두 쓴 뒤 최종 폴더명으로 바꿉니다. 처리 오류가 나면 준비 폴더를 제거합니다. OS 강제 종료로 남은 `.incomplete-*` 폴더는 완료 산출물이 아닙니다. JSON의 모르는 필드도 유지합니다. 복사한 이미지 해시를 다시 확인합니다. Mock은 pilot 결과만 만들며 production은 정확한 3,000건과 OpenAI coverage를 요구합니다.


## 0.1.10: 읽기/쓰기와 평가

- SQLAlchemy 엔진은 프로젝트 경로별 최대 16개를 재사용합니다. NullPool 연결은 작업마다 새로 열고 닫으므로 스레드 사이에 연결을 공유하지 않습니다.
- 읽기 전용 조회는 BEGIN과 query_only를 사용합니다. 쓰기는 BEGIN IMMEDIATE로 충돌 확인과 이력 추가를 원자적으로 처리합니다. WAL은 자동으로 켜지 않습니다.
- 검수 버튼·자동 초안 저장의 DB 처리는 QThread에서 실행하고 결과만 UI로 전달합니다. 저장 중 중복 입력과 이동을 막고 성공 후 이동합니다. 직접 호출하는 동기 save는 내부 작업·검증용으로 유지합니다.
- 검수 이미지 캐시는 프로젝트·샘플·원본 경로·파일 크기·수정 시각에 연결하며 최대 3항목/64MiB입니다. 차이 영상은 필요할 때 백그라운드로 생성합니다.
- 파일 내보내기는 읽기 스냅샷 뒤 DB 잠금 밖에서 staging에 생성합니다. 원본 재검증과 짧은 쓰기 트랜잭션의 gate/검수 revision 재확인 후 게시합니다. 변경 또는 실패 시 미완성 폴더를 정리합니다.
- Golden/품질/준비의 영상 동일성은 고유 후보와 같은 decoded RGB 기준입니다. 기존 계획에는 해당 계획의 원본 검증 규칙을 유지합니다.
- 종합 F1은 schema의 parent/fixed가 없는 주요 5개 라벨의 confusion counts를 합산한 micro입니다. 라벨별 지표와 분리하며 coverage와 부분 검수 평가를 표시합니다. 전부 음성이어서 TP+FP+FN=0이면 종합 F1을 정의하지 않습니다.
- schema v6은 attempt_diagnostics만 추가합니다. 요청 ID, 종료 이유, 영상 준비/요청 시간이며 API Key나 요청 영상을 저장하지 않습니다. 확인된 사용량을 가진 잘림/거부 응답도 실패 비용에 기록합니다. 미확정 원격 결과의 예약액은 보존합니다.
- 기본 prompt v6은 새 작업에만 적용합니다. 저장된 작업의 모델·프롬프트·스키마 hash는 바꾸지 않습니다.

## 2026-10-15 미배포 수정

스키마 7은 job_reservation_events만 추가합니다. 기존 프로젝트를 열면 백업한 뒤 전환하며 모델·프롬프트·검수·과거 예약액은 바꾸지 않습니다. 예약 추정치 변경은 프로젝트 잠금, 이전 값 확인, 사유·시간 이력으로 관리합니다. 구 설정의 해시는 저장된 JSON 필드로 검증하여 새 선택 필드 추가가 작업 재개를 막지 않게 합니다.

영상 준비와 토큰 추정은 쓰기 잠금 밖에서 실행합니다. API 전송 직전 짧은 쓰기 트랜잭션에서 누적 사용액+RUNNING/UNKNOWN 예약액+이번 예약액을 검사하고 attempt를 생성합니다. worker는 프로젝트 단위로 하나만 실행되므로 동시 호출이 같은 예산을 소비하지 않습니다. 재시도도 별도 예약하며 불명확한 이전 비용은 유지합니다. 사용량이 확인된 실패도 비용을 기록하고 예약 초과 시 멈춥니다.

자동 영상 계산은 공식 tile 규칙을 확인한 gpt-4o-mini/gpt-4o/gpt-4.1만 지원합니다. 그 외 모델은 명시한 장당 추정치를 사용하며 미입력은 전송 전에 중지합니다. 프롬프트·사용자 지시·응답 스키마의 UTF-8 바이트 수와 여유분, 출력 한도를 포함합니다. 기존 input_token_reserve는 최소 예약량으로 유지하며 실제 계산량이 크면 늘립니다. 보수적 추정이며 공급자 과금 한도는 아닙니다.

평가 정책 scene-f1-v1은 주요 5개 라벨 OR로 만든 장면 단위 F1을 대표로 추가하고 기존 micro 집계를 보조로 유지합니다. 모델 평가 payload에는 정답 지문·해시·스키마와 사례별 이진 정답/예측을 추가합니다. core/evaluation.py는 같은 고정 정답·전건 예측을 검증하고 전후 JSON/수동 CSV를 별도 exports에 저장합니다. 구형 집계는 표시하되 개별 예측이 없으면 장면 점수를 복원하지 않습니다. 추가 테이블/마이그레이션은 없습니다. 실제 학습 코드는 외부이며 UI 비교/저장은 기존 background 경로를 사용합니다.
