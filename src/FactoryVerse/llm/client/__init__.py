"""LLM client abstraction layer.

This module provides pluggable LLM clients with a unified interface:
- LLMClient ABC with chat_completion method
- OpenAICompatibleClient for OpenAI, PrimeIntellect, etc.
- AnthropicClient for Claude models
- Factory functions for common providers

Usage:
    from FactoryVerse.llm.client import create_openai_client, create_anthropic_client

    client = create_openai_client(api_key="...", model="gpt-4o")
    response = client.chat_completion(messages, tools)
"""

from FactoryVerse.llm.client.base import (
    LLMClient,
    ChatMessage,
    ToolCall,
)
from FactoryVerse.llm.client.openai_compatible import OpenAICompatibleClient
from FactoryVerse.llm.client.factory import (
    create_openai_client,
    create_prime_intellect_client,
)

__all__ = [
    "LLMClient",
    "ChatMessage",
    "ToolCall",
    "OpenAICompatibleClient",
    "create_openai_client",
    "create_prime_intellect_client",
]
