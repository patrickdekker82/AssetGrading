"""Language-model components (chapter 9). The app works fully without them."""

import os
from collections.abc import Mapping

from app.ai.config import AiConfig, load_ai_config

__all__ = ["AiConfig", "load_ai_config", "make_client"]


def make_client(ai: AiConfig, env: Mapping[str, str] | None = None):
    """An Anthropic client when the API key is set, otherwise None (template text only)."""
    key = (env if env is not None else os.environ).get(ai.api_key_env, "").strip()
    if not key:
        return None
    from app.ai.client import AnthropicClient

    return AnthropicClient(key)
