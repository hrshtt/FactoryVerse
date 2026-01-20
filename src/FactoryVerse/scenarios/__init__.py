"""Scenario adapters for FactoryVerse.

This module provides type-safe Python interfaces to Factorio scenarios'
remote interfaces. Adapters bridge the gap between Tier 2 (scenario loaded)
and Tier 4 (runtime) by exposing scenario-specific capabilities.

Supported Scenarios:
    - lab-grid: 8x8 grid of isolated cells for parallel multi-agent evaluation

Usage:
    >>> from FactoryVerse.scenarios import get_scenario_adapter, LabGridAdapter
    >>>
    >>> # Get adapter by name (with auto-availability check)
    >>> adapter = get_scenario_adapter("lab-grid", rcon)
    >>> if adapter:
    ...     result = adapter.create_agent_in_cell(cell_index=5)
    >>>
    >>> # Or use directly if you know the scenario
    >>> lab_grid = LabGridAdapter(rcon)
    >>> if lab_grid.is_available():
    ...     config = lab_grid.config
    ...     print(f"Grid: {config.grid_size}x{config.grid_size}")

Integration with Environment:
    The Environment module automatically loads scenario adapters at Tier 4
    initialization. Access via:

    >>> env = Environment.for_agent(scenario="lab-grid", ...)
    >>> await env.initialize(up_to=Tier.RUNTIME)
    >>> lab_grid = env.tier4.scenario  # LabGridAdapter instance
"""

from FactoryVerse.scenarios.base import (
    ScenarioAdapter,
    ScenarioError,
    Position,
    BoundingBox,
)
from FactoryVerse.scenarios.lab_grid import (
    LabGridAdapter,
    GridConfig,
    CellStatus,
    AgentCreationResult,
    ResetResult,
    AgentInfo,
)
from FactoryVerse.scenarios.registry import (
    get_scenario_adapter,
    detect_scenario,
    auto_load_adapter,
    register_adapter,
    get_registered_adapters,
)

__all__ = [
    # Base types
    "ScenarioAdapter",
    "ScenarioError",
    "Position",
    "BoundingBox",
    # Lab Grid
    "LabGridAdapter",
    "GridConfig",
    "CellStatus",
    "AgentCreationResult",
    "ResetResult",
    "AgentInfo",
    # Registry
    "get_scenario_adapter",
    "detect_scenario",
    "auto_load_adapter",
    "register_adapter",
    "get_registered_adapters",
]
