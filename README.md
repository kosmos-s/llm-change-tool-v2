# LLM Change Tool v2

Local-first Windows 데스크톱 항공영상 변화탐지 학습데이터 검수 도구입니다.

**Python 3.11 · PySide6 · SQLAlchemy · SQLite · Pydantic · OpenAI SDK**로 새로 구현했습니다. 중앙 서버나 NAS 상시 연결 없이 내 PC에서 작업합니다. 기존 JPG/JSON을 수정하지 않고, 최종 검수 결과를 기존 엘컴텍 JSON 구조로 별도 내보냅니다.

**0.1.1 UI 개선:** 단계별 왼쪽 메뉴, 선명한 글자와 버튼, 검수 불일치 강조, 요약·표 중심의 결과 화면을 제공합니다. [화면 미리보기](docs/ui-refresh.md)

## 바로 실행

Windows Portable은 [최신 GitHub Release](https://github.com/kosmos-s/llm-change-tool-v2/releases/latest)에서 `LLMChangeTool-<버전>-Windows-Portable.zip`을 받습니다. 압축을 모두 풀고 `LLMChangeTool/LLMChangeTool.exe`를 실행하세요. `_internal` 폴더를 함께 유지해야 합니다. SHA256은 같은 Release의 `.sha256` 파일로 확인할 수 있습니다. EXE는 코드 서명되지 않았습니다.

소스 실행은 Python **3.11 64비트**를 설치한 뒤:

```powershell
git clone https://github.com/kosmos-s/llm-change-tool-v2.git
cd ./llm-change-tool-v2
```

최초 한 번 `setup.bat`, 이후 `run.bat`으로 시작합니다. 첫 설치에 인터넷이 필요합니다. Mock 검수 흐름에는 API 키가 필요하지 않습니다.

## 작업 순서

1. **프로젝트**: 새 프로젝트를 로컬 디스크에 생성합니다.
2. **데이터 · AI 분석**: `train/val/test`를 포함하는 데이터 루트를 Import합니다. 품질 오류가 0인지 확인합니다.
3. 시험 실행은 `시험용 / mock`, 실제 작업은 `본작업 / openai`를 선택합니다. 본작업은 `errors/train`, `errors/val`, `errors/test`에서 각 1,000건을 정확히 고정합니다.
4. **이 설정으로 작업 만들기** → **분석 시작 / 이어하기**. OpenAI 사용 시 현재 모델 단가를 입력하고 이미지 전송/유료 호출을 확인합니다.
5. **비교하고 검수하기** → **이미지 검수**에서 검수자 이름을 입력하고 라벨을 확정합니다. 자동 저장은 임시 저장이며, `저장`이 완료 판정입니다.
6. **품질 · 내보내기**: Final Gate 통과 후 JPG/JSON을 내보냅니다. 시험용 출력은 manifest에 `pilot`, 본작업 출력은 `production`으로 구분됩니다.
7. 팀 검수 결과는 **팀 검수 · 복원**에서 ZIP으로 교환하고 충돌을 해결합니다.
8. **통계 · 모델 평가**에서 작업 현황, GPT↔Human 지표, Golden Dataset, Baseline/Retrained 모델 평가를 확인합니다.

처음부터 시험할 데이터가 없다면:

```powershell
.venv\Scripts\python -c "from pathlib import Path; from llm_change_tool.core.demo import generate_dataset; generate_dataset(Path('demo-data'))"
```

`demo-data`는 실제 기업 데이터가 아닌 생성된 6건의 합성 이미지/JSON입니다. 프로젝트는 이 폴더 바깥에 생성하세요.

## 데이터 규칙

- 지원 레이아웃: `dataset/{train,val,test}` 또는 `{train,val,test}`, `errors/{train,val,test}`, `dataset/errors/{train,val,test}`.
- `*_combined.json` + `*_combined.jpg` 또는 `*_left.jpg`/`*_right.jpg` 쌍. combined는 왼쪽 T1, 오른쪽 T2입니다.
- 원본 JSON: `Artifact`, `Tree`, `forest`, `farmland`, `water`, `artifact_detail`의 라벨을 읽습니다. `o/x`, 0/1, bool 값을 지원합니다. 알 수 없는 메타데이터는 보존합니다.
- 내부 라벨은 [label_schema_v1.json](src/llm_change_tool/resources/label_schemas/label_schema_v1.json)에 정의합니다. 26.03.24 가이드가 기준입니다.
- 원본 JSON 바이트와 파일 SHA256, 상대경로를 기록합니다. 동일 데이터 재Import는 중복 저장하지 않습니다. 내용이 바뀌면 기존 결과와 섞지 않도록 새 프로젝트 사용을 요구합니다.
- DB는 로컬 디스크에 둡니다. NAS 공유 DB나 중앙 서버를 운영하지 않습니다.

## 구현 기능

| 영역 | 제공 기능 |
|---|---|
| 프로젝트 | 생성/열기, project.db, schema migration, 무결성 점검, 백업/새 폴더 복원 |
| Import | 이미지/JSON scan, split/error type, 해시, 검증, 중복·split 누출 검출, 재Import |
| AI | Mock/OpenAI provider, 프롬프트·모델·설정 고정, 토큰·비용 기록 |
| Job | 상태·항목 DB 저장, 일시정지/취소/재개/Retry, OS lock 기반 crash recovery |
| 검수 | 원본/AI/최종 라벨, 근거·신뢰도, 필터, 동기화 확대/이동, fit/100%, 차이 영상·깜박임, 임시 저장, Undo, 이력 |
| Export | 계획 고정, Final Gate, 원본 호환 JSON, 이미지, manifest |
| 팀 | ZIP manifest/해시 검증, NEW/SAME/CONFLICT, 명시적 충돌 해결 |
| 평가 | DB 통계, label별 Precision/Recall/F1/F2, Golden 기준 Run 비교, 별도 모델 평가 |
| 배포 | PyInstaller portable, Linux/Windows 테스트, Windows GitHub Release |

## 검증 / 개발

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate ; Linux: source .venv/bin/activate
python -m pip install -r requirements-lock.txt
python -m pip install -e ".[dev]"
python scripts/check_secrets.py
python -m compileall -q src
python -m ruff check .
python -m ruff format --check .
python -m pytest -q
python -m llm_change_tool --self-test
```

테스트에서는 유료 API를 호출하지 않습니다. Ubuntu의 headless 검증은 `QT_QPA_PLATFORM=offscreen`을 사용합니다. Qt 오류가 나면 `libegl1`, `libopengl0` 설치 여부를 확인합니다. Windows 빌드는 `build_windows.bat`으로 실행합니다.

- [사용 가이드](docs/user-guide.md)
- [아키텍처 / DB 구조](docs/architecture.md)
- [개발 및 검증 보고서](docs/implementation-report.md)
- [보안 / 비용 주의사항](SECURITY.md)

실제 기업 데이터와 유료 OpenAI 호출, 사용자 Windows PC 동작은 별도 수용 검증이 필요합니다. 단가 기반 비용 제한은 예상액 관리이며 provider의 실제 청구 상한을 보장하지 않습니다.
