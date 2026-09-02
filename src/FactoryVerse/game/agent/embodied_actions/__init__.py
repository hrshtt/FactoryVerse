"""Embodied actions module - exports all embodied action classes.

This module provides the public API for embodied agent actions including:
- Movement and pathfinding
- Entity placement and building
- Inventory management
- Entity operations (recipe setting, filters, etc.)
- Crafting
- Research
- ReachableView queries (unified entity and resource queries, now at agent level)

Note: 
- Mining is not a top-level action. Resources have a .mine() method.
  MiningAction is internal infrastructure used by resource objects.
- Ghost building and placement hints are now at agent level:
  - FactoryVerse.agent.placement_hints (PlacementHints, GhostPlan, etc.)
"""

# Core action classes
from FactoryVerse.game.agent.embodied_actions.walking import MovementAction
from FactoryVerse.game.agent.embodied_actions.place_entity import PlacementAction, EntityPlaced, GhostRemoved
from FactoryVerse.game.agent.embodied_actions.inventory import AgentInventory
from FactoryVerse.game.agent.embodied_actions.entity_operations import EntityOperationsAction
# MiningAction is internal - not exported (used by resource objects)
from FactoryVerse.game.agent.embodied_actions.crafting import CraftingAction
from FactoryVerse.game.agent.embodied_actions.research import ResearchAction
__all__ = [
    # Core actions
    "MovementAction",
    "PlacementAction",
    "EntityPlaced",
    "GhostRemoved",
    "AgentInventory",
    "EntityOperationsAction",
    # MiningAction intentionally not exported - internal infrastructure
    "CraftingAction",
    "ResearchAction",
    # ReachableView is now at agent level (agent.reachable_view)
]
