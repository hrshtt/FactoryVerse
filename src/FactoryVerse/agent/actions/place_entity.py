"""Entity placement action implementation with dataclass response types.

Handles all entity placement operations: place entities, remove ghosts.

Ghost Tracking:
    Ghost entities are tracked by the fv_snapshot mod and stored in DuckDB.
    When placing ghosts with a label, the label is passed to RCON and stored
    in the ghost table. Query ghosts via remote_view.get_ghosts(sql).
"""

from dataclasses import dataclass
from typing import Optional, Union, Dict, TYPE_CHECKING
import logging

from FactoryVerse.factory.types import MapPosition, Direction
from FactoryVerse.agent.models import ActionResponse

if TYPE_CHECKING:
    from ..infra.rcon_handler import RconHandler
    from FactoryVerse.factory.item.base import PlaceableItemName

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
    
    Ghost Tracking:
        Ghosts are tracked by fv_snapshot mod → DuckDB ghost table.
        No in-memory tracking needed. Query via remote_view.get_ghosts(sql).
    """

    def __init__(self, rcon_handler: "RconHandler"):
        """Initialize placement action.

        Args:
            rcon_handler: RCON handler for command execution
        """
        self._rcon = rcon_handler

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
            label: Optional label for tracking/grouping placed entities

        Returns:
            EntityPlaced response with placement result and metadata

        Raises:
            RuntimeError: If RCON command fails
        
        Note:
            Entity tracking is handled by fv_snapshot mod. The label is passed
            to RCON and stored in the snapshot. Query entities by label via:
            - Entities: remote_view.get_entities("SELECT * FROM map_entity WHERE label = 'my_label'")
            - Ghosts: remote_view.get_ghosts("SELECT * FROM ghost WHERE label = 'my_label'")
        """
        # Build and execute RCON command
        # Pass label to RCON for ghost tracking in fv_snapshot
        cmd = self._rcon.build_command(
            "place_entity", entity_name, position, direction, ghost, label
        )
        response_dict = self._rcon.execute_and_parse_json(cmd)
        return EntityPlaced.from_dict(response_dict)

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
        
        Note:
            Ghost removal is tracked by fv_snapshot mod. The ghost table
            is automatically updated when ghosts are destroyed.
        """
        # Convert MapPosition to dict if needed
        if hasattr(position, "x") and hasattr(position, "y"):
            pos_dict = {"x": position.x, "y": position.y}
        else:
            pos_dict = position

        # Build and execute RCON command
        cmd = self._rcon.build_command("remove_ghost", entity_name, pos_dict)
        response_dict = self._rcon.execute_and_parse_json(cmd)
        return GhostRemoved.from_dict(response_dict)
