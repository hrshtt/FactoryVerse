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

from openai import OpenAI, BadRequestError

from FactoryVerse.infra.llm.client.base import (
    LLMClient,
    ChatMessage,
    ChatCompletionResult,
    ChatCompletionUsage,
    ToolCall,
)

logger = logging.getLogger(__name__)


def apply_cache_control_to_static_prefix(
    messages: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Mark the leading system message as a prompt-cache breakpoint (Anthropic semantics).

    Anthropic prompt caching is a prefix match: a ``cache_control`` breakpoint on
    the stable prefix (tool definitions render before system, so a breakpoint on
    the system block caches tools + system together) lets every subsequent call
    read that prefix from cache (~0.1x cost) instead of re-processing it.

    OpenAI-compatible gateways that front Anthropic models (e.g. OpenRouter,
    Prime Intellect) accept this as a content-block annotation on the message:

        {"role": "system",
         "content": [{"type": "text", "text": ..., "cache_control": {"type": "ephemeral"}}]}

    Only the FIRST system message is annotated, and only when its content is a
    plain string. Message order and content text are never changed; the input
    list is not mutated (a new list with a replaced first element is returned).

    Args:
        messages: Conversation history in OpenAI chat format.

    Returns:
        A new messages list with the static prefix annotated, or the original
        list unchanged if there is no leading annotatable system message.
    """
    if not messages:
        return messages

    first = messages[0]
    if first.get("role") != "system" or not isinstance(first.get("content"), str):
        # Nothing to annotate (no system prefix, or already block-structured).
        return messages

    annotated = {
        **first,
        "content": [
            {
                "type": "text",
                "text": first["content"],
                "cache_control": {"type": "ephemeral"},
            }
        ],
    }
    return [annotated, *messages[1:]]


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
        cache_static_prefix: bool = False,
    ):
        """Initialize OpenAI-compatible client.

        Args:
            api_key: API key for authentication
            model: Model name/identifier
            base_url: API base URL (None for OpenAI default)
            default_headers: Additional headers for all requests
            organization: OpenAI organization ID
            timeout: Request timeout in seconds
            cache_static_prefix: Annotate the leading system message with an
                Anthropic ``cache_control`` breakpoint so the static prefix
                (system prompt + tools) is served from the prompt cache across
                calls. Only enable for Anthropic models behind gateways that
                pass the annotation through (OBS-2). If the gateway rejects the
                annotation, the client logs a warning, retries the request
                without it once, and disables it for the rest of the session.
        """
        self._model = model
        self._cache_static_prefix = cache_static_prefix
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
        # OBS-2: annotate the static prefix as a prompt-cache breakpoint.
        # Message order and content are unchanged; only the leading system
        # message gains a cache_control annotation.
        request_messages = messages
        cache_applied = False
        if self._cache_static_prefix:
            request_messages = apply_cache_control_to_static_prefix(messages)
            cache_applied = request_messages is not messages

        # Build request kwargs
        kwargs: Dict[str, Any] = {
            "model": self._model,
            "messages": request_messages,
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
        try:
            response = self._client.chat.completions.create(**kwargs)
        except BadRequestError as e:
            if not cache_applied:
                raise
            # The gateway rejected the cache_control annotation. Degrade loudly:
            # disable prefix caching for the rest of the session and retry once
            # with the unannotated messages.
            logger.warning(
                "Prompt-cache annotation rejected by API (%s); "
                "disabling static-prefix caching for this session and retrying once.",
                e,
            )
            self._cache_static_prefix = False
            kwargs["messages"] = messages
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
            # OBS-2 observability: surface cached-prefix hits when the
            # gateway reports them (OpenAI-style prompt_tokens_details.
            # cached_tokens, or Anthropic-style cache_read_input_tokens).
            details = getattr(response.usage, "prompt_tokens_details", None)
            cached = getattr(details, "cached_tokens", None) if details else None
            if cached is None:
                cached = getattr(response.usage, "cache_read_input_tokens", None)
            usage = ChatCompletionUsage(
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
                cached_prompt_tokens=cached,
            )

        return ChatCompletionResult(
            message=message,
            usage=usage,
            finish_reason=choice.finish_reason,
            model=response.model,
        )
