"""Actionable feedback for persisted provider/queue error codes."""

ERRORS = {
    "http_401": "인증 실패 · API Key를 확인한 뒤 실패 항목 재시도를 준비하세요.",
    "http_403": "접근 거부 · API Key의 프로젝트·모델 접근 권한을 확인하세요.",
    "http_429": "요청 제한 또는 사용 한도 · API 계정의 한도를 확인하고 잠시 후 재시도하세요.",
    "connection_or_timeout": "연결·시간 초과 · 인터넷을 확인한 뒤 재시도하세요. 이전 요청의 과금 여부는 미확정입니다.",
    "malformed_output": "응답 형식 오류 · 실패 항목을 재시도하고 반복되면 모델·프롬프트 설정을 검토하세요.",
    "refused_or_truncated": "응답 거절·길이 초과 · 실패 항목을 확인하고 반복되면 분석 설정을 검토하세요.",
    "missing_token_usage": "사용량 정보 누락 · 과금 내역 확인 후 재시도하세요.",
    "interrupted_unknown_outcome": "처리 중 앱 종료 · 실패 항목을 재시도하세요. 이전 요청의 과금 여부는 미확정입니다.",
    "Estimated cost limit reached": "예상 비용 한도 도달 · ‘선택 작업 예산 변경’ 후 ‘분석 시작 / 이어하기’를 누르세요.",
    "Actual usage exceeded reserve; inspect pricing/reserve": "실제 사용량이 예약액을 초과했습니다. 단가·사용량을 확인한 뒤 재개하세요.",
    "Retry requested": "실패 항목을 다시 대기 상태로 바꿨습니다. ‘분석 시작 / 이어하기’를 누르세요.",
}


def explain_error(code):
    if code.startswith("http_5"):
        return "AI 서버 오류 · 잠시 후 실패 항목을 재시도하세요."
    return ERRORS.get(code, code)
