from dataclasses import dataclass
from typing import Protocol


@dataclass
class ProviderResponse:
    raw: str
    input_tokens: int = 0
    output_tokens: int = 0
    request_id: str | None = None
    finish_reason: str | None = None


class ProviderFailure(RuntimeError):
    def __init__(self, code: str, retryable: bool = False, response=None):
        super().__init__(code)
        self.retryable = retryable
        self.response = response


class Provider(Protocol):
    def predict(self, images, prompt: str, config) -> ProviderResponse: ...
