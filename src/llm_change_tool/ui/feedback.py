"""Korean user messages; persisted error codes remain unchanged for diagnostics."""

import hashlib
import re

ERRORS = {
    "http_401": "인증 실패 · API Key 수정 후 ‘인증·결제 수정 후 실패 복구’를 사용하세요.",
    "http_403": "접근 거부 · API Key의 프로젝트·모델 접근 권한을 확인하세요.",
    "http_429": "요청 제한 또는 사용 한도 · API 계정의 한도를 확인하고 잠시 후 재시도하세요.",
    "connection_or_timeout": "연결·시간 초과 · 인터넷을 확인한 뒤 재시도하세요. 이전 요청의 과금 여부는 미확정입니다.",
    "malformed_output": "응답 형식 오류 · 실패 항목을 재시도하고 반복되면 모델·프롬프트 설정을 검토하세요.",
    "refused_or_truncated": "응답 거절·길이 초과 · 실패 항목을 확인하고 반복되면 분석 설정을 검토하세요.",
    "response_refused": "AI가 응답을 거부했습니다. 입력 영상과 분석 지침을 확인하세요. 확인된 토큰 사용량은 비용에 기록됩니다.",
    "response_truncated": "AI 응답이 출력 한도 등으로 끝까지 생성되지 않았습니다. 출력 한도와 모델 설정을 확인하세요.",
    "empty_response": "AI가 사용할 수 있는 라벨을 반환하지 않았습니다. 실패 항목과 모델 설정을 확인하세요.",
    "missing_token_usage": "사용량 정보 누락 · 일반 재시도에서 제외됩니다. 원격 결과·과금 내역을 확인하세요.",
    "interrupted_unknown_outcome": "처리 중 앱 종료 · 원격 결과 미확정으로 일반 재시도에서 제외됩니다. 이전 요청의 결과·과금 내역을 확인하세요.",
    "insufficient_quota": "API 결제 한도 부족 · 충전·한도 수정 후 ‘인증·결제 수정 후 실패 복구’를 사용하세요.",
    "Estimated cost limit reached": "예상 비용 한도 도달 · ‘선택 작업 예산 변경’ 후 ‘분석 시작 / 이어하기’를 누르세요.",
    "Actual usage exceeded reserve; inspect pricing/reserve": "실제 사용량이 예약액을 초과했습니다. 단가·사용량을 확인한 뒤 재개하세요.",
    "Retry requested": "실패 항목을 다시 대기 상태로 바꿨습니다. ‘분석 시작 / 이어하기’를 누르세요.",
}

MESSAGES = {
    "Keep dataset and project folders separate": "프로젝트 폴더와 원본 데이터 폴더를 서로 다른 위치에 두세요.",
    "Dataset content changed": "원본 데이터 내용이 변경되었습니다. 기존 결과는 보존되며, 변경된 데이터는 새 프로젝트에서 사용하세요.",
    "Dataset quality errors": "작업을 막는 데이터 품질 문제가 있습니다. 품질 확인에서 차단 사유를 확인하세요.",
    "JSON exceeds": "JSON 파일은 2MB 이하로 준비하세요.",
    "Select common dataset root": "train·val·test를 포함하는 공통 상위 폴더를 선택하세요.",
    "Duplicate logical key": "Windows에서 같은 이름으로 처리되는 샘플이 중복되어 있습니다. 파일 이름을 확인하세요.",
    "Case-insensitive filename collision": "대소문자만 다른 파일 이름이 충돌합니다. 원본 담당자에게 이름 확인을 요청하세요.",
    "Missing T1/T2 counterpart": "과거·현재 영상 중 짝이 되는 파일이 없습니다. 영상 쌍을 확인하세요.",
    "Missing combined image": "JSON에 연결되는 통합 영상 또는 과거·현재 영상 쌍이 없습니다.",
    "T1/T2 dimensions differ": "과거·현재 영상의 크기가 다릅니다. 같은 크기의 영상 쌍을 준비하세요.",
    "Combined image width must be even": "좌우 통합 영상의 가로 크기는 짝수여야 합니다. 영상 구성을 확인하세요.",
    "Stored original hash mismatch": "저장된 원본 검증값이 일치하지 않습니다. 원본과 프로젝트 기록을 확인하세요.",
    "Stored original labels mismatch": "저장된 원본 라벨이 일치하지 않습니다. 원본과 프로젝트 기록을 확인하세요.",
    "Backup integrity check failed": "백업 검증에 실패했습니다. 다른 백업과 저장 경로를 확인하세요.",
    "Stale or invalid work plan": "작업 계획 또는 후보 정보가 현재 데이터와 일치하지 않습니다. 원본을 확인하고 새 계획을 만드세요.",
    "Work plan contains held candidates": "작업 계획에 보류된 후보가 포함되어 있습니다. 보류 원인을 해결한 뒤 다시 선정하세요.",
    "Production plan must match frozen": "본작업의 분할별 수량이 확정 계획과 다릅니다. 목표 배분을 확인하세요.",
    "Source changed during preparation": "데이터 준비 중 원본이 변경되었습니다. 원본 검증 후 다시 준비하세요.",
    "Invalid plan mode": "시험용 또는 본작업 중 올바른 작업 모드를 선택하세요.",
    "Empty plan": "작업 계획에 선정된 샘플이 없습니다. 후보 수량과 선정 조건을 확인하세요.",
    "Invalid quality mode": "품질 확인 모드를 시험용 또는 본작업으로 선택하세요.",
    "Invalid golden purpose/split": "기준 데이터의 목적과 분할을 확인하세요. 학습용은 train, 평가용은 val 또는 test입니다.",
    "Invalid action": "지원하지 않는 작업입니다. 현재 상태에서 사용할 수 있는 버튼을 선택하세요.",
    "Invalid ZIP path/duplicate sample": "ZIP에 안전하지 않은 경로나 중복 샘플이 있습니다. 올바른 검수 패키지를 선택하세요.",
    "Invalid sample ID": "검수 패키지의 샘플 식별자가 올바르지 않습니다.",
    "Unexpected or unsafe ZIP member": "ZIP에 예상하지 못한 파일 또는 안전하지 않은 경로가 있습니다.",
    "Package ID reused": "같은 패키지 식별자로 서로 다른 내용이 전달되었습니다. 새 패키지를 요청하세요.",
    "Invalid reason": "검수 근거의 형식 또는 길이가 올바르지 않습니다.",
    "Invalid English reason": "영문 근거의 형식 또는 길이가 올바르지 않습니다.",
    "Choose local or incoming": "내 검수 또는 가져온 검수 중 사용할 결과를 선택하세요.",
    "missing label": "필요한 라벨이 누락되었습니다. 라벨 항목을 확인하세요.",
    "Expecting": "JSON 문법이 올바르지 않습니다. 항목 이름·값·구분자를 확인하세요.",
    "Unterminated string": "JSON 문자열이 끝나지 않았습니다. 따옴표와 파일 내용을 확인하세요.",
    "Extra data": "JSON 뒤에 불필요한 내용이 있습니다. 파일 내용을 확인하세요.",
    "Invalid control character": "JSON 문자열에 허용되지 않는 제어 문자가 있습니다.",
    "파일 무결성/파싱 오류를 먼저 해결하세요:": "원본 파일 검증에 문제가 있습니다. 품질 확인에서 해당 파일과 문제를 확인하세요.",
    "Reviewer name is required": "검수자 이름을 1~120자로 입력한 뒤 다시 저장하세요.",
    "Review changed since loading": "다른 작업에서 검수 내용이 변경되어 저장하지 못했습니다. 입력 내용을 확인한 뒤 새로고침하고 다시 저장하세요.",
    "No review to undo": "되돌릴 검수 기록이 없습니다.",
    "Invalid review": "검수 내용이 올바르지 않습니다. 라벨과 검수 상태를 확인하세요.",
    "Reason too long": "검수 근거는 최대 10,000자로 입력하세요.",
    "Source integrity": "원본 파일 검증에 문제가 있습니다. 품질 확인에서 해당 파일과 문제를 확인하세요.",
    "Dataset quality/integrity": "데이터 품질 또는 원본 파일 검증에 문제가 있습니다. 품질 확인에서 해결할 항목을 확인하세요.",
    "Dataset folder not found": "데이터 폴더를 찾을 수 없습니다. 폴더 위치를 다시 선택하세요.",
    "Record not found": "필요한 작업 기록을 찾을 수 없습니다. 프로젝트와 선택 작업을 확인하세요.",
    "Another project worker is active": "이 프로젝트에서 다른 작업이 실행 중입니다. 작업이 끝난 뒤 다시 시도하세요.",
    "OpenAI API key is required": "API Key를 입력한 뒤 분석을 시작하세요.",
    "Golden set name required": "평가 기준 데이터의 이름을 입력하세요.",
    "Golden set not found": "평가 기준 데이터를 찾을 수 없습니다. 기준 데이터를 먼저 만들고 다시 선택하세요.",
    "Human-confirmed reviews required": "사람이 완료한 검수 항목이 없습니다. 검수를 완료한 뒤 기준 데이터를 만드세요.",
    "Model name required": "평가할 모델의 이름을 입력하세요.",
    "Model predictions must cover exactly": "예측 파일의 샘플 목록이 평가 기준과 다릅니다. 누락되거나 추가된 항목을 확인하세요.",
    "Prediction file too large": "예측 파일은 20MB 이하로 준비하세요.",
    "Non-empty equal-size arrays required": "비교할 정답과 예측의 개수가 같고 평가 항목이 있어야 합니다.",
    "Binary integer values required": "정답과 예측 라벨은 정수 0 또는 1이어야 합니다.",
    "Label keys do not match schema": "라벨 항목이 현재 기준과 다릅니다. 누락되거나 추가된 라벨을 확인하세요.",
    "Labels must be integer 0 or 1": "완료 라벨은 정수 0(없음) 또는 1(변화)이어야 합니다.",
    "Draft labels must": "초안 라벨은 0(없음), 1(변화) 또는 미확정이어야 합니다.",
    "Detail requires parent label": "인공물 세부 변화가 있으면 인공물 라벨도 변화로 설정하세요.",
    "Guideline excludes": "최신 지침에서 제외된 도로 표식 라벨은 0으로 설정하세요.",
    "Missing original label": "원본에 필요한 라벨이 없습니다. 품질 확인 후 사람이 라벨을 확정하세요.",
    "duplicate JSON key": "JSON에 같은 항목이 중복되어 있습니다. 원본 담당자에게 파일 확인을 요청하세요.",
    "JSON root must": "JSON 파일의 최상위 형식이 올바르지 않습니다. 파일을 확인하세요.",
    "non-finite JSON": "JSON에 사용할 수 없는 숫자 값이 있습니다. 파일을 확인하세요.",
    "invalid binary label": "라벨 값이 0 또는 1이 아닙니다. 원본 라벨을 확인하세요.",
    "Unsafe relative path": "파일 경로가 안전한 상대 경로가 아닙니다. 데이터 폴더 구성을 확인하세요.",
    "Source path escapes": "파일 경로가 데이터 폴더 밖을 가리킵니다. 데이터 폴더 구성을 확인하세요.",
    "Final Gate blocked": "최종 검증을 통과하지 못했습니다. 남은 검수와 AI 오류, 원본 파일 문제를 확인하세요.",
    "Export destination overlaps": "원본 폴더와 겹치는 위치로 내보낼 수 없습니다. 별도 출력 폴더를 선택하세요.",
    "Source image changed during export": "내보내기 중 원본 이미지가 변경되었습니다. 원본을 확인한 뒤 다시 검증하세요.",
    "No completed/deferred reviews": "내보낼 완료 또는 보류 검수 기록이 없습니다.",
    "ZIP exceeds": "검수 ZIP은 50MB 이하로 준비하세요.",
    "ZIP size/count/duplicate": "ZIP의 크기·파일 수 또는 중복 항목이 허용 기준을 벗어났습니다.",
    "Unsupported ZIP member": "검수 ZIP에 지원하지 않는 파일이 있습니다. 올바른 검수 패키지를 선택하세요.",
    "Invalid package": "검수 패키지의 형식이 올바르지 않습니다. 원본 패키지를 다시 받아 확인하세요.",
    "Package project/plan/run": "패키지의 프로젝트·작업 계획 또는 AI 결과가 현재 작업과 다릅니다.",
    "Review belongs to a different": "가져온 검수가 현재 AI 결과 또는 원본 버전과 다릅니다.",
    "Review SHA256 mismatch": "검수 파일의 무결성 검증에 실패했습니다. 원본 패키지를 다시 받아 확인하세요.",
    "Sample identity mismatch": "패키지의 샘플이 현재 데이터와 일치하지 않습니다.",
    "Local review changed": "충돌 확인 중 내 검수가 변경되었습니다. 최신 내용으로 충돌을 다시 확인하세요.",
    "Incoming review is stale": "가져온 검수가 이전 결과를 기준으로 합니다. 최신 검수 패키지가 필요합니다.",
    "Cancelled jobs cannot resume": "취소한 작업은 먼저 다시 열어야 이어서 실행할 수 있습니다.",
    "Prompt is empty": "분석 지침이 비어 있습니다. 기본 지침을 불러오거나 지침을 입력하세요.",
    "Production requires actual": "본작업에는 실제 AI 분석 결과가 필요합니다. 모의 분석은 시험용으로 사용하세요.",
    "Run configuration/schema": "작업 설정 또는 라벨 기준이 변경되었습니다. 현재 설정으로 새 작업을 만드세요.",
    "Run prompt hash mismatch": "작업에 저장된 지침이 변경되었습니다. 현재 지침으로 새 작업을 만드세요.",
    "Enter current USD prices": "선택한 모델의 입력·출력 토큰 단가를 확인해 입력하세요.",
    "Invalid sample count": "표본 수가 올바르지 않습니다. 선정 가능한 수량 안에서 입력하세요.",
    "orphan_image": "JSON과 연결되지 않은 이미지입니다. 후보 제외 내역을 확인하세요.",
    "split_leakage": "다른 데이터 분할에 같은 영상이 있습니다. 평가 데이터 누수를 확인하세요.",
    "duplicate_image": "같은 내용의 이미지가 중복 등록되어 있습니다.",
    "source_labels": "원본 라벨에 누락 또는 모순이 있어 사람의 확인이 필요합니다.",
    "label_conflict": "같은 영상의 원본 라벨이 서로 달라 보류되었습니다.",
    "incomplete_duplicate_labels": "중복 영상에 불완전한 라벨이 있어 보류되었습니다.",
    "required human review unresolved": "필수 검수를 완료하세요.",
    "deferred/draft/stale human review": "보류·초안 또는 이전 결과의 검수를 확인하세요.",
    "unresolved API error or missing success": "AI 오류를 해결하고 분석을 완료하세요.",
    "missing comparison/review-list entry": "비교를 실행해 검수 목록을 만드세요.",
    "stale comparison": "현재 AI 결과로 비교를 다시 실행하세요.",
    "AI job is not COMPLETED": "AI 분석이 아직 모두 성공하지 않았습니다. 실패 항목과 대기 항목을 확인하세요.",
}


def explain_error(code):
    code = str(code)
    if code.startswith("http_5"):
        return "AI 서버 오류 · 잠시 후 실패 항목을 재시도하세요."
    if code in ERRORS:
        return ERRORS[code]
    for prefix, message in MESSAGES.items():
        if code.startswith(prefix):
            return message
    if "database is locked" in code:
        return "다른 작업이 데이터를 저장하고 있습니다. 잠시 후 다시 시도하세요."
    if "No such file" in code or code == "FileNotFoundError":
        return "필요한 파일을 찾을 수 없습니다. 파일 위치와 데이터 경로를 확인하세요."
    if "Permission denied" in code or code == "PermissionError":
        return "파일에 접근할 권한이 없습니다. 폴더 권한과 다른 프로그램의 사용 여부를 확인하세요."
    if re.search("[가-힣]", code):
        return code
    identifier = hashlib.sha256(code.encode()).hexdigest()[:8]
    return f"작업을 완료하지 못했습니다. 상세 기록을 확인하세요. 오류 식별번호: {identifier}"
