"""Curated OpenAI vision models and pinned estimate prices.

Prices are USD per 1M tokens from the official OpenAI model pages, checked
2026-09-30. They are frozen into each run so old cost records stay auditable.
"""

from dataclasses import dataclass

PRICE_CHECKED_AT = "2026-09-30"


@dataclass(frozen=True)
class ModelSpec:
    model: str
    label: str
    input_price: float
    output_price: float


OPENAI_MODELS = (
    ModelSpec("gpt-4o-mini", "GPT-4o mini · 호환성 우선", 0.15, 0.60),
    ModelSpec("gpt-6-luna", "GPT-6 Luna · 추천 · 저비용", 0.10, 0.50),
    ModelSpec("gpt-6.1-sol", "GPT-6.1 Sol · 추천 · 품질 우선", 2.00, 10.00),
)

_BY_ID = {spec.model: spec for spec in OPENAI_MODELS}


def model_spec(model: str) -> ModelSpec:
    try:
        return _BY_ID[model]
    except KeyError as exc:
        raise ValueError(
            "지원 모델을 선택하세요. 모델과 자동 단가 목록은 앱 업데이트로 관리됩니다."
        ) from exc
