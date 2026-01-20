"""Scenario adapter registry and auto-detection.

Provides automatic detection and loading of scenario adapters based on
the running Factorio scenario.

Usage:
    >>> from FactoryVerse.scenarios.registry import get_scenario_adapter, detect_scenario
    >>>
    >>> # Auto-detect scenario from running game
    >>> scenario_name = detect_scenario(rcon)
    >>> adapter = get_scenario_adapter(scenario_name, rcon)
    >>>
    >>> # Or get adapter by known name
    >>> adapter = get_scenario_adapter("lab-grid", rcon)
"""

import logging
from typing import Dict, Optional, Type

from FactoryVerse.scenarios.base import ScenarioAdapter, RCONClientProtocol

logger = logging.getLogger(__name__)

# Registry of scenario name -> adapter class
_ADAPTER_REGISTRY: Dict[str, Type[ScenarioAdapter]] = {}


def register_adapter(adapter_class: Type[ScenarioAdapter]) -> Type[ScenarioAdapter]:
    """Register a scenario adapter class.

    Can be used as a decorator:
        @register_adapter
        class MyScenarioAdapter(ScenarioAdapter):
            scenario_name = "my-scenario"
            ...

    Args:
        adapter_class: ScenarioAdapter subclass to register

    Returns:
        The adapter class (for decorator use)
    """
    name = adapter_class.scenario_name
    _ADAPTER_REGISTRY[name] = adapter_class
    logger.debug(f"Registered scenario adapter: {name}")
    return adapter_class


def get_registered_adapters() -> Dict[str, Type[ScenarioAdapter]]:
    """Get all registered adapter classes.

    Returns:
        Dict mapping scenario name to adapter class
    """
    return _ADAPTER_REGISTRY.copy()


def get_scenario_adapter(
    scenario_name: str,
    rcon: RCONClientProtocol,
    require_available: bool = True,
) -> Optional[ScenarioAdapter]:
    """Get an adapter instance for a scenario.

    Args:
        scenario_name: Name of the scenario (e.g., "lab-grid")
        rcon: RCON client for communicating with Factorio
        require_available: If True, return None if interface not available

    Returns:
        ScenarioAdapter instance, or None if:
        - No adapter registered for this scenario
        - require_available=True and interface not available in game
    """
    adapter_class = _ADAPTER_REGISTRY.get(scenario_name)

    if adapter_class is None:
        logger.debug(f"No adapter registered for scenario: {scenario_name}")
        return None

    adapter = adapter_class(rcon)

    if require_available and not adapter.is_available():
        logger.debug(f"Adapter for {scenario_name} not available (interface missing)")
        return None

    logger.info(f"Loaded scenario adapter: {scenario_name}")
    return adapter


def detect_scenario(rcon: RCONClientProtocol) -> Optional[str]:
    """Detect which scenario is running by checking available interfaces.

    Iterates through registered adapters and returns the first one
    whose remote interface is available.

    Args:
        rcon: RCON client for communicating with Factorio

    Returns:
        Scenario name if detected, None otherwise
    """
    for name, adapter_class in _ADAPTER_REGISTRY.items():
        adapter = adapter_class(rcon)
        if adapter.is_available():
            logger.info(f"Detected scenario: {name}")
            return name

    logger.debug("No known scenario detected")
    return None


def auto_load_adapter(rcon: RCONClientProtocol) -> Optional[ScenarioAdapter]:
    """Auto-detect scenario and return appropriate adapter.

    Combines detect_scenario() and get_scenario_adapter() for convenience.

    Args:
        rcon: RCON client for communicating with Factorio

    Returns:
        ScenarioAdapter instance if a known scenario is detected, None otherwise
    """
    scenario_name = detect_scenario(rcon)
    if scenario_name is None:
        return None
    return get_scenario_adapter(scenario_name, rcon, require_available=False)


# =============================================================================
# Register built-in adapters
# =============================================================================

def _register_builtin_adapters():
    """Register all built-in scenario adapters."""
    # Import here to avoid circular imports
    from FactoryVerse.scenarios.lab_grid import LabGridAdapter

    register_adapter(LabGridAdapter)


# Auto-register on module import
_register_builtin_adapters()
