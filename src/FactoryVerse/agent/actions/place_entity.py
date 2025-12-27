"""Entity placement action implementation with dataclass response types.

Handles all entity placement operations: place entities, remove ghosts.
"""

from dataclasses import dataclass
from typing import Optional, Union, Dict, TYPE_CHECKING
import logging

from FactoryVerse.dsl.types import MapPosition, Direction
from FactoryVerse.agent.models import ActionResponse

if TYPE_CHECKING:
    from ..infra.rcon_handler import RconHandler
    from ..ghost.manager import GhostManager
    from FactoryVerse.dsl.item.base import PlaceableItemName

logger = logging.getLogger(__name__)


# =============================================================================
# ACTION RESPONSE TYPES
# =============================================================================


@dataclass
class EntityPlaced(ActionResponse):
    """Response when entity or ghost is placed.

    RCON Contract: RemoteInterface.lua place_entity.returns

    Returned immediately when place() is called. Contains placement result
    and metadata about the placed entity.
    """

    entity_name: str = ""
    position: Optional[Dict[str, float]] = None
    direction: Optional[int] = None
    is_ghost: bool = False
    tick: int = 0

    @property
    def placed_position(self) -> Optional[MapPosition]:
        """Get placed position as MapPosition."""
        if self.position:
            return MapPosition(x=self.position["x"], y=self.position["y"])
        return None


@dataclass
class GhostRemoved(ActionResponse):
    """Response when ghost entity is removed.

    RCON Contract: RemoteInterface.lua remove_ghost.returns

    Returned when remove_ghost() is called.
    """

    entity_name: str = ""
    position: Optional[Dict[str, float]] = None
    tick: int = 0

    @property
    def removed_position(self) -> Optional[MapPosition]:
        """Get removed position as MapPosition."""
        if self.position:
            return MapPosition(x=self.position["x"], y=self.position["y"])
        return None


# =============================================================================
# PLACEMENT ACTION
# =============================================================================


class PlacementAction:
    """Entity placement action implementation.

    Owns all placement logic:
    - place(): Place entity or ghost on the map
    - remove_ghost(): Remove a ghost entity

    All methods return structured dataclass response types for type safety.
    """

    def __init__(
        self,
        rcon_handler: "RconHandler",
        ghost_manager: Optional["GhostManager"] = None,
    ):
        """Initialize placement action.

        Args:
            rcon_handler: RCON handler for command execution
            ghost_manager: Optional ghost manager for tracking placed ghosts
        """
        self._rcon = rcon_handler
        self._ghost_manager = ghost_manager

    def place(
        self,
        entity_name: "PlaceableItemName",
        position: Union[Dict[str, float], MapPosition],
        direction: Optional[Direction] = None,
        ghost: bool = False,
        label: Optional[str] = None,
    ) -> EntityPlaced:
        """Place an entity on the map.

        Args:
            entity_name: Entity prototype name to place
            position: MapPosition or dict with x, y coordinates
            direction: Optional direction for placement
            ghost: Whether to place as ghost entity (default: False)
            label: Optional label for ghost entities (Python-only, for grouping)

        Returns:
            EntityPlaced response with placement result and metadata

        Raises:
            RuntimeError: If RCON command fails
        """
        # Build and execute RCON command
        cmd = self._rcon.build_command(
            "place_entity", entity_name, position, direction, ghost
        )
        response_dict = self._rcon.execute_and_parse_json(cmd)
        result = EntityPlaced.from_dict(response_dict)

        # Track ghost if placed and ghost manager available
        if ghost and result.success and self._ghost_manager:
            pos = result.position or (
                position
                if isinstance(position, dict)
                else {"x": position.x, "y": position.y}
            )
            self._ghost_manager.add_ghost(
                position=pos,
                entity_name=entity_name,
                label=label,
                placed_tick=result.tick,
            )
        elif not ghost and result.success and self._ghost_manager:
            # If placing a real entity, check if we're replacing a tracked ghost
            pos_dict = (
                position
                if isinstance(position, dict)
                else {"x": position.x, "y": position.y}
            )
            if self._ghost_manager.remove_ghost(
                position=pos_dict, entity_name=entity_name
            ):
                logger.info(
                    f"Ghost at {pos_dict} for {entity_name} replaced by real entity."
                )

        return result

    def remove_ghost(
        self, entity_name: str, position: Union[Dict[str, float], MapPosition]
    ) -> GhostRemoved:
        """Remove a ghost entity from the map.

        Args:
            entity_name: Entity prototype name to remove
            position: Entity position

        Returns:
            GhostRemoved response with removal result

        Raises:
            RuntimeError: If RCON command fails
        """
        # Convert MapPosition to dict if needed
        if hasattr(position, "x") and hasattr(position, "y"):
            pos_dict = {"x": position.x, "y": position.y}
        else:
            pos_dict = position

        # Build and execute RCON command
        cmd = self._rcon.build_command("remove_ghost", entity_name, pos_dict)
        response_dict = self._rcon.execute_and_parse_json(cmd)
        result = GhostRemoved.from_dict(response_dict)

        # Remove from tracking if successful and ghost manager available
        if result.success and self._ghost_manager:
            self._ghost_manager.remove_ghost(position=pos_dict, entity_name=entity_name)

        return result
