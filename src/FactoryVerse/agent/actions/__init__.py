"""Agent actions module - exports all action classes and utilities.

This module provides the public API for agent actions including:
- Movement and pathfinding
- Entity placement and building
- Inventory management
- Entity operations (recipe setting, filters, etc.)
- Ghost building and placement hints
- Mining and crafting
- Research
"""

# Core action classes
from FactoryVerse.agent.actions.walking import MovementAction
from FactoryVerse.agent.actions.place_entity import PlacementAction, EntityPlaced, GhostRemoved
from FactoryVerse.agent.actions.inventory import AgentInventory
from FactoryVerse.agent.actions.entity_operations import EntityOperationsAction
from FactoryVerse.agent.actions.ghost_builder import GhostBuilderAction
from FactoryVerse.agent.actions.mining import MiningAction
from FactoryVerse.agent.actions.crafting import CraftingAction
from FactoryVerse.agent.actions.research import ResearchAction
from FactoryVerse.agent.actions.reachable import ReachableEntities, ReachableResources
# Placement hints module (new consolidated placement reasoning)
from FactoryVerse.agent.actions.placement_hints import (
    PlacementHints,
    PlacementValidator,
    GhostPlan,
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
    "MiningAction",
    "CraftingAction",
    "ResearchAction",
    "ReachableEntities",
    "ReachableResources",
    # Placement hints
    "PlacementHints",
    "PlacementValidator",
    "GhostPlan",
    "ConnectionType",
]
