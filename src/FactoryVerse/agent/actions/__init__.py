"""Agent actions module - exports all action classes and utilities.

This module provides the public API for agent actions including:
- Movement and pathfinding
- Entity placement and building
- Inventory management
- Entity operations (recipe setting, filters, etc.)
- Ghost building and placement hints
- Crafting
- Research
- Reachable queries (unified entity and resource queries)

Note: Mining is not a top-level action. Resources have a .mine() method.
MiningAction is internal infrastructure used by resource objects.
"""

# Core action classes
from FactoryVerse.agent.actions.walking import MovementAction
from FactoryVerse.agent.actions.place_entity import PlacementAction, EntityPlaced, GhostRemoved
from FactoryVerse.agent.actions.inventory import AgentInventory
from FactoryVerse.agent.actions.entity_operations import EntityOperationsAction
from FactoryVerse.agent.actions.ghost_builder import GhostBuilderAction
# MiningAction is internal - not exported (used by resource objects)
from FactoryVerse.agent.actions.crafting import CraftingAction
from FactoryVerse.agent.actions.research import ResearchAction
from FactoryVerse.agent.actions.reachable import Reachable
# Placement hints module (new consolidated placement reasoning)
from FactoryVerse.agent.actions.placement_hints import (
    PlacementHints,
    PlacementValidator,
    GhostPlan,
    ConnectionPosition,
    ConnectionType,
)

__all__ = [
    # Core actions
    "MovementAction",
    "PlacementAction",
    "EntityPlaced",
    "GhostRemoved",
    "AgentInventory",
    "EntityOperationsAction",
    "GhostBuilderAction",
    # MiningAction intentionally not exported - internal infrastructure
    "CraftingAction",
    "ResearchAction",
    "Reachable",  # Unified entity and resource queries
    # Placement hints
    "PlacementHints",
    "PlacementValidator",
    "GhostPlan",
    "ConnectionPosition",
    "ConnectionType",
]
