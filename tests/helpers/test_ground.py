"""
Test Ground Helper - Python interface to test-ground scenario.

Provides high-level helpers for:
- Resource placement (patches, circles)
- Entity placement (single, grids)
- Area management (clear, reset)
- Snapshot control (force re-snapshot)
"""

from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass

from .server import RconConnection


@dataclass
class ResourcePatch:
    """Metadata for a placed resource patch."""

    patch_id: str
    resource_name: str
    center: Tuple[float, float]
    size: int
    amount_per_tile: int
    total_tiles: int
    total_amount: int


@dataclass
class PlacedEntity:
    """Metadata for a placed entity."""

    name: str
    position: Tuple[float, float]
    entity_id: Optional[int]
    direction: Optional[int]


class TestGround:
    """
    Helper class for interacting with test-ground scenario.

    All methods are synchronous and use xpcall for error handling.
    """

    # Test area bounds (from scenario)
    AREA_SIZE = 512
    BOUNDS = {"left_top": {"x": -256, "y": -256}, "right_bottom": {"x": 256, "y": 256}}

    def __init__(self, rcon: RconConnection):
        self.rcon = rcon

    # ========================================================================
    # RESOURCE PLACEMENT
    # ========================================================================

    def place_resource_patch(
        self,
        resource_name: str,
        center_x: float,
        center_y: float,
        size: int,
        amount: int = 10000,
    ) -> ResourcePatch:
        """
        Place a square resource patch.

        Args:
            resource_name: Resource name (e.g., "iron-ore", "copper-ore")
            center_x, center_y: Center position
            size: Side length of square patch
            amount: Amount per tile

        Returns:
            ResourcePatch with metadata
        """
        result = self.rcon.call(
            "test_ground",
            "place_resource_patch",
            resource_name,
            center_x,
            center_y,
            size,
            amount,
        )

        return ResourcePatch(
            patch_id=result["patch_id"],
            resource_name=result["resource_name"],
            center=(result["center"]["x"], result["center"]["y"]),
            size=result["size"],
            amount_per_tile=result["amount_per_tile"],
            total_tiles=result["total_tiles"],
            total_amount=result["total_amount"],
        )

    def place_iron_patch(
        self, x: float, y: float, size: int = 32, amount: int = 10000
    ) -> ResourcePatch:
        """Convenience method for placing iron ore patch."""
        return self.place_resource_patch("iron-ore", x, y, size, amount)

    def place_copper_patch(
        self, x: float, y: float, size: int = 32, amount: int = 10000
    ) -> ResourcePatch:
        """Convenience method for placing copper ore patch."""
        return self.place_resource_patch("copper-ore", x, y, size, amount)

    def place_coal_patch(
        self, x: float, y: float, size: int = 32, amount: int = 10000
    ) -> ResourcePatch:
        """Convenience method for placing coal patch."""
        return self.place_resource_patch("coal", x, y, size, amount)

    def place_stone_patch(
        self, x: float, y: float, size: int = 32, amount: int = 10000
    ) -> ResourcePatch:
        """Convenience method for placing stone patch."""
        return self.place_resource_patch("stone", x, y, size, amount)

    # ========================================================================
    # ENTITY PLACEMENT
    # ========================================================================

    def place_entity(
        self,
        entity_name: str,
        x: float,
        y: float,
        direction: Optional[int] = None,
        force: str = "player",
    ) -> PlacedEntity:
        """
        Place an entity at a position.

        Args:
            entity_name: Entity prototype name
            x, y: Position
            direction: Direction (0-7), None for default
            force: Force name

        Returns:
            PlacedEntity with metadata
        """
        result = self.rcon.call(
            "test_ground",
            "place_entity",
            entity_name,
            {"x": x, "y": y},
            direction,
            force,
        )

        if not result.get("success"):
            raise RuntimeError(
                f"Failed to place {entity_name}: {result.get('error', 'unknown')}"
            )

        meta = result["metadata"]
        return PlacedEntity(
            name=meta["name"],
            position=(meta["position"]["x"], meta["position"]["y"]),
            entity_id=meta.get("entity_id"),
            direction=meta.get("direction"),
        )

    def place_entity_grid(
        self,
        entity_name: str,
        start_x: float,
        start_y: float,
        rows: int,
        cols: int,
        spacing_x: float = 2.0,
        spacing_y: float = 2.0,
    ) -> List[PlacedEntity]:
        """
        Place entities in a grid pattern.

        Returns list of placed entities (may be fewer than rows*cols if some fail).
        """
        result = self.rcon.call(
            "test_ground",
            "place_entity_grid",
            entity_name,
            start_x,
            start_y,
            rows,
            cols,
            spacing_x,
            spacing_y,
        )

        entities = []
        for ent in result.get("entities", []):
            if ent:
                entities.append(
                    PlacedEntity(
                        name=entity_name,
                        position=(ent["position"]["x"], ent["position"]["y"]),
                        entity_id=ent.get("unit_number"),
                        direction=ent.get("direction"),
                    )
                )

        return entities

    # ========================================================================
    # AREA MANAGEMENT
    # ========================================================================

    def clear_area(
        self,
        left_top: Tuple[float, float],
        right_bottom: Tuple[float, float],
        preserve_characters: bool = True,
    ) -> int:
        """
        Clear all entities in a bounding box.

        Args:
            left_top: (x, y) of top-left corner
            right_bottom: (x, y) of bottom-right corner
            preserve_characters: If True, don't destroy player characters

        Returns:
            Number of entities cleared
        """
        bounds = {
            "left_top": {"x": left_top[0], "y": left_top[1]},
            "right_bottom": {"x": right_bottom[0], "y": right_bottom[1]},
        }

        result = self.rcon.call(
            "test_ground", "clear_area", bounds, preserve_characters
        )
        return result.get("cleared_count", 0)

    def reset_test_area(self) -> None:
        """Reset entire test area to clean state (512x512 lab tiles, no entities)."""
        self.rcon.call("test_ground", "reset_test_area")

    # ========================================================================
    # SNAPSHOT CONTROL
    # ========================================================================

    def force_resnapshot(
        self, chunk_coords: Optional[List[Tuple[int, int]]] = None
    ) -> int:
        """
        Force re-snapshot of specified chunks.

        Args:
            chunk_coords: List of (x, y) chunk coordinates, or None for all test area chunks

        Returns:
            Number of chunks enqueued
        """
        if chunk_coords is not None:
            lua_chunks = [{"x": x, "y": y} for x, y in chunk_coords]
        else:
            lua_chunks = None

        result = self.rcon.call("test_ground", "force_resnapshot", lua_chunks)
        return result.get("chunks_enqueued", 0)

    # ========================================================================
    # VALIDATION
    # ========================================================================

    def validate_resource_at(self, resource_name: str, x: float, y: float) -> bool:
        """Check if a resource exists at a position."""
        result = self.rcon.call(
            "test_ground", "validate_resource_at", resource_name, {"x": x, "y": y}
        )
        return result.get("valid", False)

    def validate_entity_at(self, entity_name: str, x: float, y: float) -> bool:
        """Check if an entity exists at a position."""
        result = self.rcon.call(
            "test_ground", "validate_entity_at", entity_name, {"x": x, "y": y}
        )
        return result.get("valid", False)

    # ========================================================================
    # METADATA
    # ========================================================================

    def get_metadata(self) -> Dict[str, Any]:
        """Get test scenario metadata (tracked resources, entities, bounds)."""
        return self.rcon.call("test_ground", "get_test_metadata")
