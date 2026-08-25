"""LLM client abstraction layer.

This module provides pluggable LLM clients with a unified interface:
- LLMClient ABC with chat_completion method
- OpenAICompatibleClient, which backs every provider (all of them speak the
  OpenAI chat-completions wire format; a "provider" is a base_url + auth pair)
- Factory functions for common providers: openai, prime_intellect, deepseek,
  azure, local

Claude models are reached as `anthropic/claude-*` model ids through an
OpenAI-compatible gateway (e.g. prime_intellect), not via a separate client.

Usage:
    from FactoryVerse.infra.llm.client import create_deepseek_client

    client = create_deepseek_client(model="deepseek-v4-pro")  # DEEPSEEK_API_KEY
    response = client.chat_completion(messages, tools)
"""

from FactoryVerse.infra.llm.client.base import (
    LLMClient,
    ChatMessage,
    ToolCall,
)
from FactoryVerse.infra.llm.client.openai_compatible import OpenAICompatibleClient
from FactoryVerse.infra.llm.client.factory import (
    create_openai_client,
    create_prime_intellect_client,
    create_deepseek_client,
    create_client_from_env,
    default_model_for_provider,
    DEFAULT_MODELS,
)

__all__ = [
    "LLMClient",
    "ChatMessage",
    "ToolCall",
    "OpenAICompatibleClient",
    "create_openai_client",
    "create_prime_intellect_client",
    "create_deepseek_client",
    "create_client_from_env",
    "default_model_for_provider",
    "DEFAULT_MODELS",
]
