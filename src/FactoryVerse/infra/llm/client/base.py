"""Abstract base class for LLM clients.

Defines the contract that all LLM clients must implement.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


@dataclass
class ToolCall:
    """Represents a tool call requested by the LLM.

    Attributes:
        id: Unique identifier for this tool call
        name: Name of the function to call
        arguments: JSON-encoded arguments string
    """

    id: str
    name: str
    arguments: str  # JSON-encoded string

    def parse_arguments(self) -> Dict[str, Any]:
        """Parse arguments JSON into a dictionary."""
        import json

        return json.loads(self.arguments)


@dataclass
class ChatMessage:
    """Normalized chat message from LLM.

    Attributes:
        role: Message role ('assistant', 'user', 'system', 'tool')
        content: Text content (may be None for tool-call-only messages)
        tool_calls: List of tool calls if the LLM requested any
        name: Function name (for tool results)
        tool_call_id: ID of the tool call this is responding to
    """

    role: str
    content: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None
    name: Optional[str] = None
    tool_call_id: Optional[str] = None

    @property
    def has_tool_calls(self) -> bool:
        """Check if this message contains tool calls."""
        return self.tool_calls is not None and len(self.tool_calls) > 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to OpenAI-compatible message dict."""
        result: Dict[str, Any] = {"role": self.role}

        if self.content is not None:
            result["content"] = self.content
        elif self.tool_calls:
            # APIs require content field on assistant messages with tool_calls
            result["content"] = ""

        if self.tool_calls:
            result["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": tc.arguments,
                    },
                }
                for tc in self.tool_calls
            ]

        if self.name is not None:
            result["name"] = self.name

        if self.tool_call_id is not None:
            result["tool_call_id"] = self.tool_call_id

        return result


@dataclass
class ChatCompletionUsage:
    """Token usage information from a completion."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    # OBS-2 observability: prompt tokens served from the provider's prompt
    # cache (OpenAI prompt_tokens_details.cached_tokens / Anthropic
    # cache_read_input_tokens). None = the gateway reported nothing, which
    # is NOT evidence caching failed — only that it is unobservable.
    cached_prompt_tokens: Optional[int] = None


@dataclass
class ChatCompletionResult:
    """Result of a chat completion call.

    Attributes:
        message: The assistant's response message
        usage: Token usage information
        finish_reason: Why generation stopped ('stop', 'tool_calls', 'length')
        model: The model that generated the response
    """

    message: ChatMessage
    usage: Optional[ChatCompletionUsage] = None
    finish_reason: Optional[str] = None
    model: Optional[str] = None


class LLMClient(ABC):
    """Abstract LLM client with OpenAI-compatible interface.

    All LLM providers should implement this interface to work with
    the FactoryVerse orchestrator.
    """

    @abstractmethod
    def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.1,
        max_tokens: Optional[int] = None,
        stop: Optional[List[str]] = None,
    ) -> ChatCompletionResult:
        """Execute chat completion with optional tool use.

        Args:
            messages: Conversation history (OpenAI format)
            tools: Tool definitions (OpenAI function calling format)
            temperature: Sampling temperature (0.0-2.0)
            max_tokens: Maximum tokens to generate
            stop: Stop sequences

        Returns:
            ChatCompletionResult with response and metadata
        """
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the model identifier."""
        pass

    @property
    def supports_tool_use(self) -> bool:
        """Check if this client supports tool/function calling."""
        return True  # Default: assume yes
