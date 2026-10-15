import base64
import io

from openai import APIConnectionError, APIStatusError, OpenAI

from llm_change_tool.core.labels import KEYS
from llm_change_tool.providers.base import ProviderFailure, ProviderResponse


def response_schema():
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["labels", "confidence", "reason", "review_required"],
        "properties": {
            "labels": {
                "type": "object",
                "additionalProperties": False,
                "required": list(KEYS),
                "properties": {k: {"type": "integer", "enum": [0, 1]} for k in KEYS},
            },
            "confidence": {"type": "number"},
            "reason": {"type": "string"},
            "review_required": {"type": "boolean"},
        },
    }


USER_INSTRUCTION = "T1(과거), T2(현재) 순서입니다. 가이드에 따라 판정하세요."


class OpenAIProvider:
    def __init__(self, api_key: str):
        if not api_key.strip():
            raise ValueError("OpenAI API key is required")
        self.api_key = api_key
        self.client = None

    def close(self):
        if self.client:
            self.client.close()
            self.client = None

    def predict(self, images, prompt, config):
        content = [{"type": "text", "text": USER_INSTRUCTION}]
        for image in images:
            buf = io.BytesIO()
            image.save(buf, format="JPEG", quality=95)
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "data:image/jpeg;base64,"
                        + base64.b64encode(buf.getvalue()).decode(),
                        "detail": config.image_detail,
                    },
                }
            )
        try:
            # Disable SDK retries: every billable attempt is reserved/persisted by our job runner.
            if self.client is None:
                self.client = OpenAI(api_key=self.api_key, timeout=config.timeout, max_retries=0)
            result = self.client.chat.completions.create(
                model=config.model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": content},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "change_labels",
                        "strict": True,
                        "schema": response_schema(),
                    },
                },
                max_completion_tokens=config.max_output_tokens,
            )
            message = result.choices[0].message
            if not result.usage:
                raise ProviderFailure("missing_token_usage")
            response = ProviderResponse(
                message.content or "",
                result.usage.prompt_tokens,
                result.usage.completion_tokens,
                getattr(result, "_request_id", None),
                result.choices[0].finish_reason,
            )
            if message.refusal:
                raise ProviderFailure("response_refused", response=response)
            if result.choices[0].finish_reason != "stop":
                raise ProviderFailure("response_truncated", response=response)
            if not message.content:
                raise ProviderFailure("empty_response", response=response)
            return response
        except APIConnectionError as exc:
            raise ProviderFailure("connection_or_timeout", True) from exc
        except APIStatusError as exc:
            body = exc.body if isinstance(exc.body, dict) else {}
            nested = body.get("error")
            nested = nested if isinstance(nested, dict) else {}
            if exc.status_code == 429 and (
                body.get("code") == "insufficient_quota"
                or nested.get("code") == "insufficient_quota"
            ):
                raise ProviderFailure("insufficient_quota") from exc
            raise ProviderFailure(
                f"http_{exc.status_code}", exc.status_code == 429 or exc.status_code >= 500
            ) from exc
