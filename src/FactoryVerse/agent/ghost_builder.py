"""Ghost builder action for building ghost entities.

This module handles building ghost entities by walking to them and placing
real entities. It works with ghost entities from:
- Remote queries (runtime.remote_view.get_ghosts())
- Reachable queries (runtime.reachable.get_ghosts())
- GhostPlan objects (from agent.placement_hints module)

All ghost entities are represented as BaseEntity with is_ghost=True.
"""

from FactoryVerse.factory.factorio_types import Direction
from typing import List, Dict, Any, TYPE_CHECKING
from dataclasses import dataclass

if TYPE_CHECKING:
    from FactoryVerse.agent.embodied_actions.walking import MovementAction
    from FactoryVerse.agent.embodied_actions.place_entity import PlacementAction
    from FactoryVerse.agent.embodied_actions.inventory import AgentInventory
    from FactoryVerse.factory.entity.base_entity import BaseEntity
    from FactoryVerse.factory.types import MapPosition
    from FactoryVerse.agent.placement_hints import GhostPlan


@dataclass
class GhostInfo:
    """Extracted ghost information for building."""

    name: str
    position: "MapPosition"
    direction: int | None = None


class GhostBuilderAction:
    """Handles building ghost entities by walking to them and placing real entities.

    This is an action class that coordinates movement and placement to
    build ghosts. It supports ghost entities from any source:
    - Remote ghosts: runtime.remote_view.get_ghosts(sql)
    - Reachable ghosts: runtime.reachable.get_ghosts()

    The GhostBuilderAction handles movement orchestration automatically.

    Example:
        >>> ghosts = remote_view.get_ghosts("SELECT * FROM ghost LIMIT 5")
        >>> result = await ghost_builder.build_ghosts(ghosts)
    """

    def __init__(
        self,
        movement: "MovementAction",
        placement: "PlacementAction",
        inventory: "AgentInventory",
    ):
        """Initialize ghost builder.

        Args:
            movement: Movement action for walking to ghost positions
            placement: Placement action for placing entities
            inventory: Agent inventory for checking available items
        """
        self._movement = movement
        self._placement = placement
        self._inventory = inventory

    def _extract_ghost_info(self, ghost: "BaseEntity") -> GhostInfo:
        """Extract name and position from a ghost entity.

        Works with both Reachable and RemoteView wrapped ghosts.
        """
        # Ghost entities have ghost_name (the entity they represent)
        # or fall back to name
        name = getattr(ghost, "ghost_name", None) or getattr(ghost, "name", "unknown")
        position = ghost.position
        direction = getattr(ghost, "direction", None)

        return GhostInfo(name=name, position=position, direction=direction)

    async def build_ghosts(
        self,
        ghosts: List["BaseEntity"],
        count: int = 10,
        strict: bool = False,
    ) -> Dict[str, Any]:
        """Build ghost entities in bulk.

        This is an async method that walks to ghost locations and builds them.
        Prints progress as it goes.

        Args:
            ghosts: List of ghost entities to build
            count: Max entities to build (default: 10)
            strict: If True, validate agent has all items before building

        Returns:
            Result dict with:
                - built_count: int (number of ghosts built)
                - failed_count: int (number of ghosts that couldn't be built)
                - total_processed: int (total ghosts processed)
                - built_ghosts: List (ghosts that were built)
                - failed_ghosts: List (ghosts that failed)
        """
        # Limit to count
        ghosts_to_build = ghosts[:count]

        if not ghosts_to_build:
            return {
                "built_count": 0,
                "failed_count": 0,
                "total_processed": 0,
                "built_ghosts": [],
                "failed_ghosts": [],
            }

        # Extract ghost info for processing
        ghost_infos = [self._extract_ghost_info(g) for g in ghosts_to_build]

        # If strict, validate inventory first
        if strict:
            inventory_items = self._inventory.item_stacks
            inventory_dict = {item.name: item.count for item in inventory_items}

            # Count required items
            required: Dict[str, int] = {}
            for info in ghost_infos:
                required[info.name] = required.get(info.name, 0) + 1

            # Check availability
            missing: Dict[str, int] = {}
            for entity_name, needed in required.items():
                available = inventory_dict.get(entity_name, 0)
                if available < needed:
                    missing[entity_name] = needed - available

            if missing:
                return {
                    "built_count": 0,
                    "failed_count": 0,
                    "total_processed": 0,
                    "built_ghosts": [],
                    "failed_ghosts": [],
                    "error": f"Insufficient items: {missing}",
                }

        # Build ghosts one by one
        built_count = 0
        failed_count = 0
        built_ghosts: List[BaseEntity] = []
        failed_ghosts: List[BaseEntity] = []

        total = len(ghosts_to_build)
        print(f"Building {total} ghosts...")

        for i, (ghost, info) in enumerate(zip(ghosts_to_build, ghost_infos), 1):
            try:
                # Walk to ghost position
                await self._movement.walk_to(info.position)

                # Place entity at position
                result = self._placement.place(
                    info.name,
                    info.position,
                    direction=Direction(info.direction),
                )

                if result.success:
                    built_count += 1
                    built_ghosts.append(ghost)
                    print(
                        f"  ({built_count}/{total}) Built {info.name} at {info.position}"
                    )
                else:
                    failed_count += 1
                    failed_ghosts.append(ghost)
                    print(
                        f"  Failed to build {info.name}: {result.message or 'Unknown'}"
                    )

            except Exception as e:
                failed_count += 1
                failed_ghosts.append(ghost)
                print(f"  Error building {info.name}: {e}")

        print(f"\nBuild summary: {built_count} built, {failed_count} failed")

        return {
            "built_count": built_count,
            "failed_count": failed_count,
            "total_processed": total,
            "built_ghosts": built_ghosts,
            "failed_ghosts": failed_ghosts,
        }

    async def build_ghost(self, ghost: "BaseEntity") -> bool:
        """Build a single ghost entity.

        Convenience method for building one ghost. Walks to the ghost
        position and places the entity.

        Args:
            ghost: Ghost entity to build

        Returns:
            True if successfully built, False otherwise
        """
        result = await self.build_ghosts([ghost], count=1)
        return result["built_count"] == 1
    
    async def build_plan(self, plan: "GhostPlan", strict: bool = False) -> Dict[str, Any]:
        """Build a GhostPlan by placing ghosts at all positions.
        
        This method commits a validated GhostPlan to the map as ghosts,
        then builds them into real entities. It's a convenience wrapper
        that combines ghost placement + building.
        
        Args:
            plan: GhostPlan object from placement_hints module
            strict: If True, validate agent has all items before building
        
        Returns:
            Result dict with build statistics (same as build_ghosts)
        
        Example:
            >>> plan = placement_hints.get_placement_line("transport-belt", start, end)
            >>> result = await ghost_builder.build_plan(plan)
        """
        if not plan.valid:
            return {
                "built_count": 0,
                "failed_count": 0,
                "total_processed": 0,
                "built_ghosts": [],
                "failed_ghosts": [],
                "error": "GhostPlan is not valid (validation failed)",
            }
        
        # Place all ghosts from the plan
        print(f"Placing {len(plan.positions)} ghosts for plan: {plan.description}")
        placed_count = 0
        
        for position, direction in plan.positions:
            try:
                # Place ghost at position with label
                self._placement.place(
                    plan.entity_name,
                    position,
                    direction=direction,
                    ghost=True,
                    label=plan.label,
                )
                placed_count += 1
            except Exception as e:
                print(f"  Failed to place ghost at {position}: {e}")
        
        print(f"Placed {placed_count}/{len(plan.positions)} ghosts")
        
        # Now query the ghosts we just placed and build them
        # We need to get them from the remote view since they're now in the DB
        # This is a bit circular - we'd need remote_view access here
        # For now, return placement stats
        return {
            "built_count": 0,
            "failed_count": 0,
            "total_processed": placed_count,
            "placed_count": placed_count,
            "error": "build_plan needs remote_view integration to query placed ghosts",
        }
