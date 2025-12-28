"""Ghost builder action for building tracked ghosts.

This module handles the actual building of tracked ghosts - walking to them
and placing entities.
"""

from typing import List, Dict, Any, TYPE_CHECKING

from .types import TrackedGhost

if TYPE_CHECKING:
    from FactoryVerse.agent.actions.walking import MovementAction
    from FactoryVerse.agent.actions.place_entity import PlacementAction
    from FactoryVerse.agent.actions.inventory import AgentInventory


class GhostBuilderAction:
    """Handles building tracked ghosts by walking to them and placing entities.

    This is an action class that coordinates movement and placement to
    build ghosts that have been tracked by GhostManager.
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

    async def build_ghosts(
        self,
        ghosts: List[TrackedGhost],
        count: int = 10,
        strict: bool = False,
    ) -> Dict[str, Any]:
        """Build tracked ghost entities in bulk.

        This is an async method that walks to ghost locations and builds them.
        Prints progress as it goes.

        Args:
            ghosts: List of TrackedGhost objects to build
            count: Max entities to build (default: 10)
            strict: If True, validate agent has all items before building

        Returns:
            Result dict with:
                - built_count: int (number of ghosts built)
                - failed_count: int (number of ghosts that couldn't be built)
                - total_processed: int (total ghosts processed)
                - built_ghosts: List[TrackedGhost] (ghosts that were built)
                - failed_ghosts: List[TrackedGhost] (ghosts that failed)
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

        # If strict, validate inventory first
        if strict:
            inventory_items = self._inventory.item_stacks
            inventory_dict = {item.name: item.count for item in inventory_items}

            # Count required items
            required: Dict[str, int] = {}
            for ghost in ghosts_to_build:
                required[ghost.name] = required.get(ghost.name, 0) + 1

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
        built_ghosts: List[TrackedGhost] = []
        failed_ghosts: List[TrackedGhost] = []

        total = len(ghosts_to_build)
        print(f"Building {total} ghosts...")

        for i, ghost in enumerate(ghosts_to_build, 1):
            try:
                # Walk to ghost position
                await self._movement.walk_to(ghost.position)

                # Place entity at position (PlacementAction.place returns EntityPlaced dataclass)
                result = self._placement.place(
                    ghost.name,
                    ghost.position,
                )

                if result.success:
                    built_count += 1
                    built_ghosts.append(ghost)
                    print(
                        f"  ({built_count}/{total}) Built {ghost.name} at {ghost.position}"
                    )
                else:
                    failed_count += 1
                    failed_ghosts.append(ghost)
                    print(
                        f"  Failed to build {ghost.name}: {result.message or 'Unknown'}"
                    )

            except Exception as e:
                failed_count += 1
                failed_ghosts.append(ghost)
                print(f"  Error building {ghost.name}: {e}")

        print(f"\nBuild summary: {built_count} built, {failed_count} failed")

        return {
            "built_count": built_count,
            "failed_count": failed_count,
            "total_processed": total,
            "built_ghosts": built_ghosts,
            "failed_ghosts": failed_ghosts,
        }
