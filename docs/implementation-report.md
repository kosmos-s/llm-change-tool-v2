# v2 1차 구현 보고서

## 목표와 범위

Phase 0~7의 Local-first 데스크톱 흐름을 새 코드로 구현했습니다. 사용자 승인 없이 원본을 바꾸거나 실제 API를 호출하지 않았습니다. 실제 기업 데이터는 저장소에 포함하지 않았습니다.

## 구현된 영역

프로젝트/SQLAlchemy/SQLite migration, 원본 불변 Import, versioned schema/prompt, OpenAI 및 Mock, persistent Job/Retry/Resume/recovery, Compare, 이미지 검수/이력, 3,000 Work Plan, Final Gate/JSON·JPG Export, 팀 ZIP/충돌, backup/restore, DB dashboard, Golden/모델 지표, PyInstaller/Windows CI를 연결했습니다.

아키텍처와 DB 테이블은 [architecture.md](architecture.md), 실행 방법은 [README](../README.md), 구체적 화면 순서는 [user-guide.md](user-guide.md)에 설명합니다.

폴더: `src/llm_change_tool/{core,storage,providers,ui,resources}` + `tests/`, `scripts/`, `docs/`, `.github/workflows/`. runtime 프로젝트의 데이터/DB/export/backup은 소스 폴더와 분리합니다.

## v1에서 참고한 것

- 26.03.24 guideline을 반영한 prompt_v5. 업무 규칙 본문을 사용하고 응답 envelope만 schema-driven labels로 변경했습니다.
- 엘컴텍 JSON 키 및 artifact_detail 매핑, unknown field 보존.
- core/detailed 비교 정책, 세부 인공물의 상위 라벨 관계.
- 작업 계획/실행 hash binding, 필수 검수/보류 Gate, portable 팀 교환의 목적.
- F2 계산 및 GPT 분석과 변화탐지 모델 평가의 분리.

v1 참고 기준: `kosmos-s/llm-change-auto` commit `066634c677ae5a182d781e411221d9420926561c`.

## v1에서 가져오지 않은 것

Streamlit UI, CSV 중심 상태 관리, checkpoint 파일 재개 방식, 출력 폴더를 찾아 최신 결과를 추측하는 방식은 사용하지 않았습니다. v1 앱 코드를 복제하지 않고 SQLite 관계와 immutable Run/review revision을 중심으로 다시 작성했습니다.

## 검증 상태

로컬 Python 3.12 및 GitHub Actions Python 3.11 환경에서 검증합니다. 합성 JPG/JSON과 가짜 HTTP 응답을 사용하며 실제 회사 데이터와 유료 API는 사용하지 않습니다.

| 검증 | 확인한 결과 |
|---|---|
| 로컬 전체 pytest | **38 passed**. 3,003건 중 정확한 3,000건 계획과 SDK transport 검사 포함 |
| Import 확장성 | 폴더 목록 반복 조회 제거. 같은 로컬 전체 테스트가 **47.23초 → 5.97초**로 단축됨; 실제 대형 JPG 성능 측정은 아님 |
| compile / Ruff / secret scan | 모두 통과 |
| 실제 PySide6 UI | Job 생성→Mock 실행→Compare→6건 검수→Gate, 프로젝트 전환/zoom 동기화 통과 |
| Linux frozen | PyInstaller 빌드, Core self-test, GUI/worker smoke 통과 |
| Windows/Linux CI | [검증 실행](https://github.com/kosmos-s/-llm-change-tool-v2/actions/runs/35169342036) 성공. 이 실행은 추가 규모/SDK 테스트 전의 33개 pytest 기준 |
| Windows Portable | 위 실행에서 실제 `LLMChangeTool.exe` 빌드 및 frozen Core/GUI/worker 검사 모두 성공 |
| 최신 브랜치 CI | [PR #1 Checks](https://github.com/kosmos-s/-llm-change-tool-v2/pull/1/checks)에 이후 38개 테스트와 Import 최적화를 포함한 실행 결과가 기록됨 |

Windows 배포본은 [GitHub Releases](https://github.com/kosmos-s/-llm-change-tool-v2/releases/latest)의 `LLMChangeTool-<버전>-Windows-Portable.zip`에서 받습니다. 버전이 바뀌면 Windows 빌드와 동결 실행 파일 검증을 거쳐 새 Release가 자동 생성됩니다. ZIP의 SHA256 검증 파일도 함께 게시됩니다. 로컬에서는 `build_windows.bat`으로 같은 Portable 폴더를 만들 수 있습니다.

## 알려진 제한 및 실제 사용자 수용 테스트

- 실제 기업 데이터의 모든 변형 스키마/이미지 크기, 유료 OpenAI 호출은 검증하지 않았습니다. 첫 실데이터는 소규모 pilot로 확인해야 합니다.
- OpenAI가 현재 모델에 대해 image input과 strict structured output을 지원해야 합니다. 모델 단가 입력은 사용자 책임이며 비용 제한은 추정치입니다.
- API 요청을 provider가 처리한 직후 프로세스가 죽으면 결과를 복구할 수 없고, Retry는 추가 비용이 발생할 수 있습니다. 보수적 예약액과 UNKNOWN 이력을 남깁니다.
- 자동 저장은 초안이며 반드시 완료 저장과 구분합니다. UI의 실제 한글 입력, HiDPI, 듀얼 모니터, 매우 큰 이미지, Windows 종료/백신 환경은 팀원 PC에서 확인해야 합니다.
- 앱 안의 이미지 데이터는 로컬 경로로 읽습니다. 네트워크 마운트 자동 탐지는 완전하지 않습니다.
- 팀 ZIP은 동일 AI 결과 문맥의 검수 교환용입니다. 독립적으로 재실행한 다른 GPT 결과에 기반한 검수는 stale 검수로 거절합니다.
- DB/ZIP 암호화, Windows 코드 서명, 자동 업데이트는 포함하지 않았습니다.
- 대량 AI 작업은 영속 Job의 순차 처리입니다. OpenAI 서버의 비동기 Batch API는 아직 연결하지 않았습니다.
- split 누출 검사는 동일 이미지 바이트 SHA256 기준입니다. 재인코딩된 동일 장소나 인접 타일의 공간적 누출까지 검출하지는 않습니다.
- 사용자가 만든 Golden Set은 현재 Run의 완료 검수 전체를 고정합니다. 소규모 전용 프로젝트로 reference set을 구성할 수 있습니다.
- Export 파일과 SQLite는 하나의 분산 transaction이 아닙니다. 폴더 확정 직후 OS가 중단되면 manifest가 있는 완료 폴더와 DB snapshot 목록이 다를 수 있습니다. `.incomplete-*` 폴더는 미완료로 취급합니다.
- 이미지 opacity slider는 제공하지 않습니다. 동기화 pan/zoom, difference와 flicker를 제공합니다.
- 모델 학습을 실행하는 도구는 아닙니다. 실제 Baseline/Retrained 예측 JSON을 받아 평가합니다.

## 다음 개선 후보

실데이터 adapter 수용 테스트 확장, 이미지 캐시/대형 데이터 페이지 단위 목록, provider-side 비동기 Batch, OS keyring, 선택형 Golden subset UI, 코드 서명/업데이트, 팀 충돌 비교 화면 개선을 고려할 수 있습니다.

## 최종 저장소 점검

| 항목 | 결과 / 처리 |
|---|---|
| dead code / TODO / 경로 | 실행 코드의 TODO/FIXME, 개발 환경 절대경로 없음. DB root 외 샘플 경로는 상대경로 |
| secret / 실데이터 | Git index의 실제 커밋 내용 검사, CI 검사, Windows setup 시 pre-commit hook 설치 |
| import / 의존성 | compileall, Ruff, 실제 패키지 import, frozen 실행으로 검사 |
| DB migration | schema 1→2 업그레이드·백업, 잘못된 DB와 미래 버전 거절, 복원 검사 |
| crash recovery | 프로젝트 OS lock, 중단 항목 UNKNOWN/FAILED, 성공 항목 중복 호출 방지 검사 |
| stale state | 원본/Run/Compare/review hash binding, revision 충돌, 프로젝트 전환 시 검수 문맥 초기화 |
| Export | 필수 검수 누락/보류/변조/Compare 누락 차단, 디스크 쓰기 실패 시 최종 폴더 미생성 |
| Windows | 한글·공백 경로 테스트, console 없는 EXE에서 결과 파일로 별도 worker 통신 |
| 배포 | PyInstaller 리소스 포함, frozen Core self-test 및 GUI/worker smoke |

## 사용자 PC에서 확인할 순서

1. Portable ZIP 전체를 풀고 `LLMChangeTool.exe` 실행, 새 프로젝트 생성/백업/복원.
2. 허가된 소량 실제 데이터로 Import 결과와 원본 엘컴텍 JSON round-trip 확인.
3. 이미지 시점·화질·동기화 zoom/pan·한글 입력·자동 임시 저장/완료 저장 확인.
4. 단가를 확인한 소량 OpenAI pilot, timeout/일시정지/종료 후 재개 확인.
5. 팀원 PC로 백업/검수 ZIP 교환, 경로 재연결 및 충돌 해결 확인.
6. 소규모 수용 검증 후 errors 각 1,000건의 production 계획으로 진행.
