# v0.1.12 자동 점검 · 진행 기록

2026-10-21 사용자 요청: "1번 자동 점검을 시작하고, Claude 사용량이 떨어지면 GPT가 이어 갈 수 있게."
이 문서는 진행 상황을 단계마다 갱신합니다. 이어받는 에이전트(GPT/Codex 포함)는
AGENTS.md → HANDOFF.md → 이 문서 순서로 읽고 **상태가 `완료`가 아닌 첫 단계부터** 이어 가세요.

## 범위와 금지 사항

- 대상: GitHub Release v0.1.12 Portable ZIP(배포본)과 같은 코드의 소스 실행.
- 사람이 해야 하는 부분은 대신하지 않습니다. 화면을 보고 쓰기 불편한 점을 찾는 일, 20건·val 50건·test 200건의
  실제 판정은 사용자 몫입니다. 에이전트가 만든 판정은 사람 정답이 아닙니다.
- **실제 검수 프로젝트를 수정하지 마세요.**
  - `artifacts/evaluation-pilot-20261015-a0799582/project`(20건)
  - `artifacts/independent-experiment-v1-781dd78f/development-project`(val 50)
  - `artifacts/independent-experiment-v1-781dd78f/holdout-project`(test 200)
  점검은 백업을 새 폴더로 복원한 **복사본**에서만 합니다. 원본 JPG/JSON은 읽기 전용입니다.
- 유료 API, 회사 서버, main 병합, 새 릴리스는 하지 않습니다(사용자 별도 지시 필요).
- 점검 결과물(복사본·캡처·내보내기)은 `artifacts/acceptance-0.1.12/`에만 둡니다. Git 제외 폴더이며 커밋하지 마세요.
- 앱 사용자 설정(레지스트리)을 건드리지 않도록 화면 점검은 임시 INI 설정을 씁니다(`scripts/capture_ui.py` 방식).

## 단계

| # | 단계 | 상태 | 결과 |
| --- | --- | --- | --- |
| 1 | 배포 ZIP 내려받기·SHA256 대조·압축 해제 (`artifacts/acceptance-0.1.12/portable/`) | 완료 | SHA256 `dd5179cc…99cf` 일치 |
| 2 | 배포 exe `--self-test`, `--gui-smoke` | 완료 | 둘 다 통과(WMI 실행, 아래 기록 참고) |
| 3 | 20건 프로젝트 백업을 복사본으로 복원, 원본 파일 해시 기록 | 대기 | |
| 4 | 복사본으로 검수 흐름: 이름 입력·자동 기억, 판정 저장(초안/완료), 되돌리기, 위치 복원, 독립 판정 숨김 | 대기 | |
| 5 | 복사본으로 Mock 재실행 → 비교 → 최종 Gate → 별도 JSON 내보내기, 원본 해시 불변 확인 | 대기 | |
| 6 | 백업·복원 화면 동작, 오류 안내 한국어 표시 | 대기 | |
| 7 | 화면 캡처(검수·독립 판정·백업 복원·품질) → 사용자 확인용 | 대기 | |
| 8 | 결과 정리, 사용자가 직접 볼 항목 목록, 인계 문서 갱신 | 대기 | |

## 이어받기 방법

- 브랜치: `fix/korean-error-messages`(main은 v0.1.12 `d72e3c9`). 점검 중 버그를 찾으면 회귀 테스트와 함께
  이 브랜치에 커밋하고 이 표의 결과 칸에 적습니다.
- 점검 스크립트는 `artifacts/acceptance-0.1.12/` 아래에 두고, 다시 실행해도 실제 프로젝트를 건드리지 않게 만드세요.
- 검증 명령은 [Claude 인계 문서](claude-handoff.md)의 「검증 명령」을 따릅니다. 전체 pytest는 11~13분 걸립니다.
- 보고는 한국어로, 변경·검증 근거·사용자 PC 확인·회사 미확정 사항을 나눠 씁니다.

## 기록

### 2026-10-21 · 1~2단계

- 배포 ZIP과 `.sha256`의 해시가 일치했습니다.
- **에이전트 셸에서 exe를 직접 실행하면 안 됩니다.** Claude Code 셸에서 `Start-Process`로 띄운 배포 exe는
  자체 점검이 종료 코드 1로 끝나고 보고서가 없었습니다(10회 이상 재현). 같은 exe를 WMI로 세션 밖에서 실행하면
  3/3 통과(2~3초)했습니다. 원인은 앱이 아니라 에이전트 실행 환경입니다. 근거는 다음과 같습니다.
  - 같은 태그 소스를 CI와 같은 Python 3.11.9 + PyInstaller 6.22.3로 다시 빌드했습니다. 배포 exe와는
    PE 시각·체크섬 8바이트만 다르고 앱 코드·내장 모듈·DLL 구성이 같았습니다.
  - 그런데도 같은 바이너리가 실행할 때마다 통과·실패가 바뀌었고, 실패한 실행에는 파이썬 오류 기록이 없었습니다.
    외부에서 강제 종료된 것으로 보입니다.
  - 배포 exe를 검사하려면 아래처럼 세션 밖에서 실행하세요.
    ```powershell
    Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = '"<exe>" --self-test --report "<절대경로>.json"'; CurrentDirectory = '<폴더>' }
    ```
    프로세스가 끝날 때까지 기다린 뒤 보고서 JSON을 확인합니다.
- `--gui-smoke`는 셸·WMI 모두 통과했습니다.
- 이 진단에서 `.venv`에 `pyinstaller==6.22.3`을 설치했습니다(`build_windows.bat`과 같은 버전).
  실패한 실행이 남긴 `%TEMP%\llm-change-selftest-*` 20개는 삭제했습니다.
