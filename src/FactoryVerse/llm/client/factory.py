"""Factory functions for creating LLM clients.

Provides convenient functions for creating clients for common providers.
"""

import os
from typing import Optional, Dict

from FactoryVerse.llm.client.base import LLMClient
from FactoryVerse.llm.client.openai_compatible import OpenAICompatibleClient


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
    model = model or os.getenv("LLM_MODEL")

    factories: Dict[str, callable] = {
        "openai": lambda: create_openai_client(model=model)
        if model
        else create_openai_client(),
        "prime_intellect": lambda: create_prime_intellect_client(model=model)
        if model
        else create_prime_intellect_client(),
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
