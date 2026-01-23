"""OpenAI-compatible LLM client.

This client works with any API that implements the OpenAI chat completions
format, including:
- OpenAI (gpt-4, gpt-4o, etc.)
- Prime Intellect (intellect-3, etc.)
- Azure OpenAI
- Local models via vLLM, Ollama, etc.
"""

import logging
from typing import List, Dict, Any, Optional

from openai import OpenAI

from FactoryVerse.infra.llm.client.base import (
    LLMClient,
    ChatMessage,
    ChatCompletionResult,
    ChatCompletionUsage,
    ToolCall,
)

logger = logging.getLogger(__name__)


class OpenAICompatibleClient(LLMClient):
    """Client for OpenAI-compatible APIs.

    Works with any API that implements the OpenAI chat completions format.

    Example:
        # OpenAI
        client = OpenAICompatibleClient(
            api_key="sk-...",
            model="gpt-4o"
        )

        # Prime Intellect
        client = OpenAICompatibleClient(
            api_key="...",
            model="intellect-3",
            base_url="https://api.pinference.ai/api/v1"
        )

        # Local vLLM
        client = OpenAICompatibleClient(
            api_key="not-used",
            model="meta-llama/Llama-3.1-70B-Instruct",
            base_url="http://localhost:8000/v1"
        )
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: Optional[str] = None,
        default_headers: Optional[Dict[str, str]] = None,
        organization: Optional[str] = None,
        timeout: float = 120.0,
    ):
        """Initialize OpenAI-compatible client.

        Args:
            api_key: API key for authentication
            model: Model name/identifier
            base_url: API base URL (None for OpenAI default)
            default_headers: Additional headers for all requests
            organization: OpenAI organization ID
            timeout: Request timeout in seconds
        """
        self._model = model
        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            default_headers=default_headers,
            organization=organization,
            timeout=timeout,
        )

        logger.info(f"Initialized OpenAI-compatible client for {model}")
        if base_url:
            logger.info(f"  Base URL: {base_url}")

    @property
    def model_name(self) -> str:
        """Return the model identifier."""
        return self._model

    def list_models(self) -> List[str]:
        """List available models from the API.

        Returns:
            List of model IDs available on this endpoint
        """
        try:
            models = self._client.models.list()
            return [m.id for m in models.data]
        except Exception as e:
            logger.warning(f"Failed to list models: {e}")
            return []

    def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.1,
        max_tokens: Optional[int] = None,
        stop: Optional[List[str]] = None,
    ) -> ChatCompletionResult:
        """Execute chat completion.

        Args:
            messages: Conversation history
            tools: Tool definitions (function calling)
            temperature: Sampling temperature
            max_tokens: Max tokens to generate
            stop: Stop sequences

        Returns:
            ChatCompletionResult with response
        """
        # Build request kwargs
        kwargs: Dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
        }

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        if stop is not None:
            kwargs["stop"] = stop

        # Make request
        logger.debug(f"Chat completion with {len(messages)} messages")
        response = self._client.chat.completions.create(**kwargs)

        # Parse response
        choice = response.choices[0]
        assistant_message = choice.message

        # Extract tool calls if present
        tool_calls = None
        if assistant_message.tool_calls:
            tool_calls = [
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=tc.function.arguments,
                )
                for tc in assistant_message.tool_calls
            ]

        # Build result
        message = ChatMessage(
            role="assistant",
            content=assistant_message.content,
            tool_calls=tool_calls,
        )

        usage = None
        if response.usage:
            usage = ChatCompletionUsage(
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
            )

        return ChatCompletionResult(
            message=message,
            usage=usage,
            finish_reason=choice.finish_reason,
            model=response.model,
        )
