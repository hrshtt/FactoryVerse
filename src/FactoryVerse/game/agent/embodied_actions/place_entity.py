"""Entity placement action implementation with dataclass response types.

Handles all entity placement operations: place entities, remove ghosts.

Ghost Tracking:
    Ghost entities are tracked by the fv_snapshot mod and stored in DuckDB.
    When placing ghosts with a label, the label is passed to RCON and stored
    in the ghost table. Query ghosts via remote_view.get_ghosts(sql).
"""

from dataclasses import dataclass
from typing import Optional, Union, Dict, Any, TYPE_CHECKING
import logging

from FactoryVerse.game.factory.types import MapPosition, Direction
from FactoryVerse.game.agent.models import ActionResponse

if TYPE_CHECKING:
    from ..infra.rcon_handler import RconHandler
    from FactoryVerse.game.factory.item.base import PlaceableItemName
    from FactoryVerse.game.factory.entity.base_entity import BaseEntity
    from .entity_operations import EntityOperationsAction
    from .walking import MovementAction

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

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EntityPlaced":
        """Create instance from dict, deriving is_ghost from entity_type."""
        # Derive is_ghost from entity_type if not explicitly set
        if "is_ghost" not in data and data.get("entity_type") == "entity-ghost":
            data = dict(data)  # Copy to avoid mutating original
            data["is_ghost"] = True

        valid_fields = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**valid_fields)


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

    def __init__(
        self,
        rcon_handler: "RconHandler",
        entity_ops: "EntityOperationsAction",
        walking_action: "MovementAction",
    ):
        """Initialize placement action.

        Args:
            rcon_handler: RCON handler for command execution
            entity_ops: EntityOperationsAction for creating BaseEntity after placement
            walking_action: MovementAction for creating entities with navigation capability
        """
        self._rcon = rcon_handler
        self._entity_ops = entity_ops
        self._walking_action = walking_action

    def place(
        self,
        entity_name: "PlaceableItemName",
        position: Union[Dict[str, float], MapPosition],
        direction: Optional[Direction] = None,
        ghost: bool = False,
        label: Optional[str] = None,
        return_entity: bool = False,
    ) -> Union[EntityPlaced, "BaseEntity"]:
        """Place an entity on the map.

        Args:
            entity_name: Entity prototype name to place
            position: MapPosition or dict with x, y coordinates
            direction: Optional direction for placement
            ghost: Whether to place as ghost entity (default: False)
            label: Optional label for tracking/grouping placed entities
            return_entity: If True and entity_ops is available, return BaseEntity instead of EntityPlaced

        Returns:
            EntityPlaced response with placement result and metadata, or BaseEntity if return_entity=True

        Raises:
            RuntimeError: If RCON command fails or if return_entity=True but entity_ops is not available

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
        result = EntityPlaced.from_dict(response_dict)

        # If requested, return BaseEntity instead
        if return_entity and not ghost:
            # Get the placed position
            placed_pos = result.placed_position
            if placed_pos is None:
                raise RuntimeError("Placement succeeded but position is missing")

            # Inspect the entity to get full entity data
            entity_data = self._entity_ops.inspect_entity(entity_name, placed_pos)

            # Create BaseEntity from the inspection data
            from FactoryVerse.game.factory.entity.create_entity import create_reachable_entity

            return create_reachable_entity(
                entity_data,
                self._entity_ops,
                self,  # self is PlacementAction, which is place_ops
                self._walking_action,
                is_ghost=False,
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
