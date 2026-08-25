"""Factory functions for creating LLM clients.

Provides convenient functions for creating clients for common providers.
"""

import os
from typing import Optional, Dict

from FactoryVerse.infra.llm.client.base import LLMClient
from FactoryVerse.infra.llm.client.openai_compatible import OpenAICompatibleClient

# DeepSeek's first-party platform endpoint (OpenAI-compatible chat completions).
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_DEFAULT_MODEL = "deepseek-v4-pro"

# Default model per provider, used when no --model / LLM_MODEL is supplied.
# Keeps `-p deepseek` from inheriting a Prime-Intellect-shaped model id.
DEFAULT_MODELS: Dict[str, str] = {
    "openai": "gpt-4o",
    "prime_intellect": "anthropic/claude-sonnet-4.6",
    "deepseek": DEEPSEEK_DEFAULT_MODEL,
    "azure": "gpt-4o",
    "local": "default",
}


def default_model_for_provider(provider: Optional[str]) -> Optional[str]:
    """Return the default model id for a provider, or None if unknown."""
    if not provider:
        return None
    return DEFAULT_MODELS.get(provider)


def _is_anthropic_model(model: Optional[str]) -> bool:
    """True when the model id names an Anthropic model (e.g. 'anthropic/claude-sonnet-4.6').

    Used to gate Anthropic-specific prompt caching (cache_control on the static
    prefix, OBS-2) on provider-agnostic gateways. Non-Anthropic models never get
    the annotation.
    """
    if not model:
        return False
    namespace = model.split("/", 1)[0].lower()
    return namespace == "anthropic" or model.lower().startswith("claude")


def create_openai_client(
    api_key: Optional[str] = None,
    model: str = "gpt-4o",
    organization: Optional[str] = None,
) -> LLMClient:
    """Create an OpenAI client.

    Args:
        api_key: OpenAI API key (default: OPENAI_API_KEY env var)
        model: Model name (default: gpt-4o)
        organization: OpenAI organization ID

    Returns:
        Configured OpenAI client
    """
    if api_key is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set")

    return OpenAICompatibleClient(
        api_key=api_key,
        model=model,
        organization=organization,
    )


def create_prime_intellect_client(
    api_key: Optional[str] = None,
    model: str = "intellect-3",
) -> LLMClient:
    """Create a Prime Intellect client.

    Args:
        api_key: Prime Intellect API key (default: PRIME_INTELLECT_API_KEY env var)
        model: Model name (default: intellect-3)

    Returns:
        Configured Prime Intellect client
    """
    if api_key is None:
        # Support both PRIME_API_KEY (legacy) and PRIME_INTELLECT_API_KEY
        api_key = os.getenv("PRIME_API_KEY") or os.getenv("PRIME_INTELLECT_API_KEY")
        if not api_key:
            raise ValueError(
                "PRIME_API_KEY or PRIME_INTELLECT_API_KEY environment variable not set"
            )

    return OpenAICompatibleClient(
        api_key=api_key,
        model=model,
        base_url="https://api.pinference.ai/api/v1",
        # OBS-2: Anthropic prompt caching for anthropic/* models served via the
        # gateway. The ~30k-token static prefix (system prompt + tools) is then
        # read from cache (~0.1x cost) instead of re-sent at full price per call.
        cache_static_prefix=_is_anthropic_model(model),
    )


def create_deepseek_client(
    api_key: Optional[str] = None,
    model: str = DEEPSEEK_DEFAULT_MODEL,
) -> LLMClient:
    """Create a client for DeepSeek's first-party platform API.

    DeepSeek exposes an OpenAI-compatible chat-completions endpoint at
    ``https://api.deepseek.com``, so this reuses OpenAICompatibleClient
    unchanged. Both current models (``deepseek-v4-flash``, ``deepseek-v4-pro``)
    support tool calls, which the agent loop requires.

    Args:
        api_key: DeepSeek API key (default: DEEPSEEK_API_KEY env var)
        model: Model name (default: deepseek-v4-pro)

    Returns:
        Configured DeepSeek client
    """
    if api_key is None:
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY environment variable not set")

    return OpenAICompatibleClient(
        api_key=api_key,
        model=model,
        base_url=DEEPSEEK_BASE_URL,
        # DeepSeek does its own context caching server-side and rejects nothing,
        # but the Anthropic cache_control annotation is meaningless here.
        cache_static_prefix=False,
    )


def create_azure_openai_client(
    api_key: Optional[str] = None,
    deployment_name: str = "gpt-4o",
    azure_endpoint: Optional[str] = None,
    api_version: str = "2024-02-15-preview",
) -> LLMClient:
    """Create an Azure OpenAI client.

    Args:
        api_key: Azure OpenAI API key (default: AZURE_OPENAI_API_KEY env var)
        deployment_name: Azure deployment name
        azure_endpoint: Azure endpoint URL (default: AZURE_OPENAI_ENDPOINT env var)
        api_version: API version

    Returns:
        Configured Azure OpenAI client
    """
    if api_key is None:
        api_key = os.getenv("AZURE_OPENAI_API_KEY")
        if not api_key:
            raise ValueError("AZURE_OPENAI_API_KEY environment variable not set")

    if azure_endpoint is None:
        azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        if not azure_endpoint:
            raise ValueError("AZURE_OPENAI_ENDPOINT environment variable not set")

    # Azure uses a different base URL format
    base_url = f"{azure_endpoint}/openai/deployments/{deployment_name}"

    return OpenAICompatibleClient(
        api_key=api_key,
        model=deployment_name,
        base_url=base_url,
        default_headers={"api-version": api_version},
    )


def create_local_client(
    base_url: str = "http://localhost:8000/v1",
    model: str = "default",
) -> LLMClient:
    """Create a client for local LLM servers (vLLM, Ollama, etc.).

    Args:
        base_url: Server URL (default: vLLM default)
        model: Model name/path

    Returns:
        Configured local client
    """
    return OpenAICompatibleClient(
        api_key="not-used",  # Local servers typically don't require auth
        model=model,
        base_url=base_url,
    )


def create_client_from_env(
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> LLMClient:
    """Create LLM client from environment configuration.

    Reads LLM_PROVIDER and LLM_MODEL environment variables.

    Args:
        provider: Provider name (override LLM_PROVIDER)
        model: Model name (override LLM_MODEL)

    Returns:
        Configured LLM client

    Raises:
        ValueError: If provider is unknown or required config is missing
    """
    provider = provider or os.getenv("LLM_PROVIDER", "prime_intellect")
    model = model or os.getenv("LLM_MODEL") or default_model_for_provider(provider)

    factories: Dict[str, callable] = {
        "openai": lambda: create_openai_client(model=model)
        if model
        else create_openai_client(),
        "prime_intellect": lambda: create_prime_intellect_client(model=model)
        if model
        else create_prime_intellect_client(),
        "deepseek": lambda: create_deepseek_client(model=model)
        if model
        else create_deepseek_client(),
        "azure": lambda: create_azure_openai_client(deployment_name=model)
        if model
        else create_azure_openai_client(),
        "local": lambda: create_local_client(model=model)
        if model
        else create_local_client(),
    }

    if provider not in factories:
        raise ValueError(
            f"Unknown LLM provider: {provider}. Known: {list(factories.keys())}"
        )

    return factories[provider]()
