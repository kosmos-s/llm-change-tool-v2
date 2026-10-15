"""Offline, conservative reservations, not provider-enforced billing caps.

Image rules checked 2026-10-15:
https://developers.openai.com/api/docs/guides/images-vision
Only explicitly documented model rules are automatic. Unknown rules require
an explicit per-image token reservation; a model name alone is not evidence.
"""

import math

from llm_change_tool.core.labels import canonical
from llm_change_tool.providers.openai import USER_INSTRUCTION, response_schema

TILE_MODELS = {"gpt-4o-mini": (2833, 5667), "gpt-4o": (85, 170), "gpt-4.1": (85, 170)}


def image_tokens(model, size, detail="high", override=None):
    width, height = size
    if width <= 0 or height <= 0:
        raise ValueError("Invalid image dimensions")
    if detail not in ("low", "high", "auto"):
        raise ValueError("Unsupported image detail")
    if model not in TILE_MODELS:
        if override is None:
            raise ValueError(
                "Image token rules are unverified; enter a per-image token reservation for this model"
            )
        return override
    base, tile = TILE_MODELS[model]
    if detail == "low":
        tokens = base
    else:
        scale = min(1, 2048 / max(width, height), 768 / min(width, height))
        width, height = max(1, math.floor(width * scale)), max(1, math.floor(height * scale))
        tokens = base + math.ceil(width / 512) * math.ceil(height / 512) * tile
    return max(tokens, override or 0)


def request_input_reserve(images, prompt, config):
    if config.provider == "mock":
        return 0
    # UTF-8 bytes deliberately overestimate text tokens without downloading a
    # tokenizer. Include system/user text, structured-output schema and framing.
    text = prompt + USER_INSTRUCTION + canonical(response_schema())
    text_tokens = len(text.encode("utf-8")) + 1024
    vision_tokens = sum(
        image_tokens(config.model, image.size, config.image_detail, config.image_token_override)
        for image in images
    )
    return max(config.input_token_reserve, math.ceil((text_tokens + vision_tokens) * 1.1))


def request_cost_reserve(images, prompt, config):
    return config.reserve(request_input_reserve(images, prompt, config))
