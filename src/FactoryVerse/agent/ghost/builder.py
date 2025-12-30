"""Ghost builder action for building ghost entities.

This module handles building ghost entities by walking to them and placing
real entities. It works with both:
- TrackedGhost objects (from GhostManager)
- Reachable[BaseEntity] ghost entities (from reachable_entities.get_ghosts())
"""

from typing import List, Dict, Any, Union, TYPE_CHECKING

from .types import TrackedGhost

if TYPE_CHECKING:
    from FactoryVerse.agent.actions.walking import MovementAction
    from FactoryVerse.agent.actions.place_entity import PlacementAction
    from FactoryVerse.agent.actions.inventory import AgentInventory
    from FactoryVerse.dsl.entity.views import Reachable
    from FactoryVerse.dsl.entity.base_entity import BaseEntity


# Type alias for ghost entities (either TrackedGhost or Reachable[ghost])
GhostLike = Union[TrackedGhost, "Reachable[BaseEntity]"]


class GhostBuilderAction:
    """Handles building ghost entities by walking to them and placing real entities.

    This is an action class that coordinates movement and placement to
    build ghosts. It supports both:
    - TrackedGhost objects (lightweight Python tracking objects)
    - Reachable[BaseEntity] with is_ghost=True (in-game ghost entities)

    The GhostBuilderAction is the recommended way to build ghosts as it
    handles movement orchestration automatically.
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

    def _extract_ghost_info(self, ghost: GhostLike) -> Dict[str, Any]:
        """Extract name and position from a ghost-like object.

        Works with both TrackedGhost and Reachable[BaseEntity] ghosts.
        """
        if isinstance(ghost, TrackedGhost):
            return {
                "name": ghost.name,
                "position": ghost.position,
                "direction": getattr(ghost, "direction", None),
            }
        else:
            # Reachable[BaseEntity] with is_ghost=True
            return {
                "name": ghost.ghost_name or ghost.name,
                "position": ghost.position,
                "direction": ghost.direction,
            }

    async def build_ghosts(
        self,
        ghosts: List[GhostLike],
        count: int = 10,
        strict: bool = False,
    ) -> Dict[str, Any]:
        """Build ghost entities in bulk.

        This is an async method that walks to ghost locations and builds them.
        Prints progress as it goes.

        Supports both TrackedGhost objects and Reachable[BaseEntity] ghost entities.

        Args:
            ghosts: List of ghost objects to build (TrackedGhost or Reachable[ghost])
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
                required[info["name"]] = required.get(info["name"], 0) + 1

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

        # Build ghosts one by one (simple approach)
        built_count = 0
        failed_count = 0
        built_ghosts: List[GhostLike] = []
        failed_ghosts: List[GhostLike] = []

        total = len(ghosts_to_build)
        print(f"Building {total} ghosts...")

        for i, (ghost, info) in enumerate(zip(ghosts_to_build, ghost_infos), 1):
            try:
                # Walk to ghost position
                await self._movement.walk_to(info["position"])

                # Place entity at position
                result = self._placement.place(
                    info["name"],
                    info["position"],
                    direction=info.get("direction"),
                )

                if result.success:
                    built_count += 1
                    built_ghosts.append(ghost)
                    print(
                        f"  ({built_count}/{total}) Built {info['name']} at {info['position']}"
                    )
                else:
                    failed_count += 1
                    failed_ghosts.append(ghost)
                    print(
                        f"  Failed to build {info['name']}: {result.message or 'Unknown'}"
                    )

            except Exception as e:
                failed_count += 1
                failed_ghosts.append(ghost)
                print(f"  Error building {info['name']}: {e}")

        print(f"\nBuild summary: {built_count} built, {failed_count} failed")

        return {
            "built_count": built_count,
            "failed_count": failed_count,
            "total_processed": total,
            "built_ghosts": built_ghosts,
            "failed_ghosts": failed_ghosts,
        }

    async def build_ghost(self, ghost: GhostLike) -> bool:
        """Build a single ghost entity.

        Convenience method for building one ghost. Walks to the ghost
        position and places the entity.

        Args:
            ghost: Ghost to build (TrackedGhost or Reachable[ghost])

        Returns:
            True if successfully built, False otherwise
        """
        result = await self.build_ghosts([ghost], count=1)
        return result["built_count"] == 1
