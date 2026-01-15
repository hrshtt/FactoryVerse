"""Base entity class and entity position helper.

Defines the core BaseEntity contract that all entity implementations inherit.
Uses Component Registry pattern for inspect() - returns EntityInspection
with capability slots populated based on isinstance checks.
"""

from enum import Enum
from typing import Optional, List, Dict, Any, TYPE_CHECKING
from FactoryVerse.factory.types import MapPosition, Direction, EntityStatus
from FactoryVerse.factory.prototypes import get_entity_prototypes, get_width_height
import math

if TYPE_CHECKING:
    from FactoryVerse.factory.item.base import ItemStack
    from FactoryVerse.agent.actions.entity_operations import EntityOperationsAction
    from FactoryVerse.agent.actions.place_entity import PlacementAction
    from FactoryVerse.agent.actions.walking import MovementAction
    from .inspection import EntityInspection


class EntityView(Enum):
    REMOTE = "remote"
    REACHABLE = "reachable"


class EntityPosition(MapPosition):
    """Position with entity-aware spatial operations.

    High-level position type that knows about entities, items, and prototypes.
    Provides spatial reasoning for placement and layout calculations.
    """

    def __init__(
        self,
        x: float,
        y: float,
        entity: Optional["BaseEntity"] = None,
    ):
        super().__init__(x, y)
        self._entity = entity

    def offset_by_entity(
        self,
        direction: Direction,
        entity: Optional["BaseEntity"] = None,
        gap: int = 0,
    ) -> "EntityPosition":
        """Calculate position offset by entity dimensions in a cardinal direction.

        Args:
            direction: Cardinal direction to offset (NORTH/SOUTH/EAST/WEST)
            entity: Entity to get dimensions from (uses parent if None)
            gap: Additional tiles of spacing (default 0 for touching)

        Returns:
            New EntityPosition offset by entity dimensions + gap
        """
        if direction is None:
            raise ValueError("direction is required")

        ref = entity or self._entity
        if ref is None:
            raise ValueError(
                "No entity provided and no parent entity bound to this position."
            )

        if not direction.is_cardinal():
            raise ValueError(
                f"Cannot offset in non-cardinal direction: {direction.name}"
            )

        tile_w = ref.tile_width
        tile_h = ref.tile_height

        if direction in (Direction.NORTH, Direction.SOUTH):
            distance = tile_h + gap
        else:
            distance = tile_w + gap

        if direction == Direction.NORTH:
            new_x, new_y = self.x, self.y - distance
        elif direction == Direction.EAST:
            new_x, new_y = self.x + distance, self.y
        elif direction == Direction.SOUTH:
            new_x, new_y = self.x, self.y + distance
        else:
            new_x, new_y = self.x - distance, self.y

        return EntityPosition(x=new_x, y=new_y)


class BaseEntity:
    """Base class for all entity implementations.

    Uses Component Registry pattern for inspection - the inspect() method
    returns an EntityInspection with capability slots populated based on
    which mixins the entity inherits from.

    **For Agents**: Entities are returned with appropriate view settings:
    - Reachable entities: Full access (can mutate entity state)
    - Remote entities: Read-only access (can inspect only)
    - Ghost entities: Limited operations (build, remove, static inspect)
    """

    # Blocked methods by view/ghost status
    _REACHABLE_ONLY = frozenset(
        {
            "pickup",
            "add_fuel",
            "add_ingredients",
            "take_products",
            "store_items",
            "take_items",
            "set_recipe",
            "build",
        }
    )
    _GHOST_BLOCKED = frozenset(
        {
            "pickup",
            "add_fuel",
            "add_ingredients",
            "take_products",
            "store_items",
            "take_items",
            "set_recipe",
        }
    )

    def __init__(
        self,
        name: str,
        position: MapPosition,
        entity_ops: "EntityOperationsAction",
        place_ops: "PlacementAction",
        walking_action: "MovementAction",
        is_ghost: bool = False,
        ghost_name: Optional[str] = None,
        view: EntityView = EntityView.REMOTE,
        **kwargs,
    ):
        """Initialize base entity.

        Args:
            name: Entity prototype name (e.g., "stone-furnace")
            position: Entity position in the world
            entity_ops: Entity operations action for game interactions
            place_ops: Placement action for placement operations
            walking_action: Movement action for navigation
            is_ghost: Whether this is a ghost entity
            ghost_name: For ghosts, the entity prototype this ghost represents
            view: Entity view type (REMOTE or REACHABLE)
        """
        self.name = name
        self._raw_position = position
        self._is_ghost = is_ghost
        self._ghost_name = ghost_name
        self._view = view
        self._prototype_cache: Optional[Dict[str, Any]] = None

        # Action dependencies (always required)
        self._entity_ops: "EntityOperationsAction" = entity_ops
        self._place_ops: "PlacementAction" = place_ops
        self._walking_action: "MovementAction" = walking_action

    # =========================================================================
    # Properties (absorbed from SpatialPropertiesMixin and PrototypeMixin)
    # =========================================================================

    @property
    def position(self) -> EntityPosition:
        """Get entity position as EntityPosition bound to this entity."""
        return EntityPosition(
            x=self._raw_position.x, y=self._raw_position.y, entity=self
        )

    async def walk_to(self, timeout: Optional[int] = None) -> "MapPosition":
        """Walk to this entity.

        Delegates to the walking action to navigate to this entity.
        Handles checking if the entity is already reachable.
        After successful walk, changes view from REMOTE to REACHABLE to enable mutations.

        Args:
            timeout: Optional timeout in seconds

        Returns:
            Final position reached

        Raises:
            WalkingUnreachableError: If entity cannot be reached
            WalkingEntityNotFoundError: If entity no longer exists
        """
        final_position = await self._walking_action.walk_to_entity(
            entity_name=self.name,
            entity_position=self.position,
            timeout=timeout,
        )
        
        # After successful walk, change view from REMOTE to REACHABLE to enable mutations
        if self._view == EntityView.REMOTE:
            self._view = EntityView.REACHABLE
        
        return final_position

    @property
    def prototype(self) -> Dict[str, Any]:
        """Get prototype data as dict (lazy-loaded)."""
        if self._prototype_cache is None:
            protos = get_entity_prototypes()
            self._prototype_cache = protos.get_prototype(self.name)
        return self._prototype_cache

    @property
    def tile_width(self) -> int:
        """Calculate tile width from prototype collision_box."""
        EPSILON = 0.001
        proto = self.prototype
        if "tile_width" in proto:
            return int(proto["tile_width"])
        if "collision_box" in proto:
            w, _ = get_width_height(proto["collision_box"])
            return int(math.ceil(w - EPSILON))
        return 0

    @property
    def tile_height(self) -> int:
        """Calculate tile height from prototype collision_box."""
        EPSILON = 0.001
        proto = self.prototype
        if "tile_height" in proto:
            return int(proto["tile_height"])
        if "collision_box" in proto:
            _, h = get_width_height(proto["collision_box"])
            return int(math.ceil(h - EPSILON))
        return 0

    @property
    def footprint(self) -> tuple:
        """Get (width, height) tuple for spatial calculations."""
        return (self.tile_width, self.tile_height)

    @property
    def is_ghost(self) -> bool:
        """Whether this is a ghost entity."""
        return self._is_ghost

    @property
    def ghost_name(self) -> Optional[str]:
        """For ghost entities, the entity prototype this ghost represents."""
        return self._ghost_name if self._is_ghost else None

    # =========================================================================
    # Inspection - Component Registry Pattern
    # =========================================================================

    def inspect(self) -> "EntityInspection":
        """Inspect entity state with live game data.

        **For Agents**: Use this to check entity status, inventories, progress, etc.
        Returns EntityInspection with capability slots populated based on entity type.

        Returns:
            EntityInspection with populated capability slots
        """
        from .inspection import EntityInspection
        from .capabilities import (
            BurnerMixin,
            ElectricMixin,
            CrafterMixin,
            MinerMixin,
            InserterMixin,
            FluidMixin,
            BeltMixin,
        )

        # For ghosts, return minimal static inspection
        if self._is_ghost:
            return EntityInspection(
                name=self.name,
                position={"x": self.position.x, "y": self.position.y},
                direction=getattr(self, "direction", None),
                is_ghost=True,
            )

        # Get live inspection data from game
        raw_data = self._entity_ops.inspect_entity(self.name, self.position)

        # Convert status to EntityStatus enum if present
        status_value = raw_data.get("status")
        status_enum = None
        if status_value is not None:
            # Status comes as integer (enum value) from Lua
            try:
                status_enum = EntityStatus(status_value)
            except (ValueError, TypeError):
                # If conversion fails, leave as None
                status_enum = None

        # Build base inspection
        inspection = EntityInspection(
            name=self.name,
            position={"x": self.position.x, "y": self.position.y},
            direction=getattr(self, "direction", None),
            status=status_enum,
            is_ghost=False,
        )

        # Populate capability slots via isinstance checks
        if isinstance(self, BurnerMixin):
            inspection.burner = self._get_burner_state(raw_data)

        if isinstance(self, ElectricMixin):
            inspection.electric = self._get_electric_state(raw_data)

        if isinstance(self, CrafterMixin):
            inspection.crafter = self._get_crafter_state(raw_data)

        if isinstance(self, MinerMixin):
            inspection.miner = self._get_miner_state(raw_data)

        if isinstance(self, InserterMixin):
            inspection.inserter = self._get_inserter_state(raw_data)

        if isinstance(self, FluidMixin):
            inspection.fluid = self._get_fluid_state(raw_data)

        if isinstance(self, BeltMixin):
            inspection.belt = self._get_belt_state(raw_data)

        # ===== Category-specific states (from implementations) =====
        from .implementations.container import Container
        from .implementations.lab import Lab
        from .implementations.accumulator import Accumulator
        from .implementations.electric_pole import ElectricPole
        from .implementations.generator import GeneratorMixin

        if isinstance(self, Container):
            inspection.container = self._get_container_state(raw_data)

        if isinstance(self, Lab):
            inspection.lab = self._get_lab_state(raw_data)

        if isinstance(self, Accumulator):
            inspection.accumulator = self._get_accumulator_state(raw_data)

        if isinstance(self, ElectricPole):
            inspection.electric_pole = self._get_electric_pole_state(raw_data)

        if isinstance(self, GeneratorMixin):
            inspection.generator = self._get_generator_state(raw_data)

        return inspection

    # =========================================================================
    # Actions
    # =========================================================================

    def __getattribute__(self, name: str):
        """Filter method access based on view and ghost status."""
        attr = super().__getattribute__(name)

        if not callable(attr) or name.startswith("_"):
            return attr

        view = super().__getattribute__("_view")
        is_ghost = super().__getattribute__("_is_ghost")

        if view == EntityView.REMOTE and name in BaseEntity._REACHABLE_ONLY:
            raise AttributeError(
                f"Cannot {name}() remotely. Entity not reachable. "
                "Use reachable_entities.get_entity() for full access."
            )

        if is_ghost and name in BaseEntity._GHOST_BLOCKED:
            raise AttributeError(
                f"Cannot {name}() on ghost entity. "
                "Ghosts are placeholders - use build() first."
            )

        return attr

    def build(self) -> Dict[str, Any]:
        """Build ghost into real entity. Ghost-only."""
        if not self._is_ghost:
            raise RuntimeError(f"Cannot build {self.name}: not a ghost entity.")

        entity_name = self._ghost_name or self.name
        result = self._place_ops.place(
            entity_name,  # type: ignore
            self.position,
            getattr(self, "direction", None),
            ghost=False,
        )
        return {"success": result.success}  # type: ignore

    def remove(self) -> bool:
        """Remove ghost entity. Ghost-only."""
        if not self._is_ghost:
            raise RuntimeError(
                f"Cannot remove {self.name} via remove(): not a ghost. Use pickup()."
            )

        entity_name = self._ghost_name or self.name
        result = self._place_ops.remove_ghost(entity_name, self.position)
        return result.success

    def pickup(self) -> List["ItemStack"]:
        """Pick up the entity and return extracted items with placement injected."""
        result = self._entity_ops.pickup_entity(self.name, self.position)
        from FactoryVerse.factory.item.create_item import create_item_stack

        if result.extracted_items:
            return [
                create_item_stack(name, count, placement=self._place_ops)
                for name, count in result.extracted_items.items()
            ]
        return []

    def __repr__(self) -> str:
        """Show entity with view prefix."""
        pos = self.position
        prefix = self._view.value.capitalize()
        entity_name = (
            f"GHOST:{self.__class__.__name__}"
            if self._is_ghost
            else self.__class__.__name__
        )
        direction = getattr(self, "direction", None)
        dir_str = f", dir={direction.name}" if direction else ""
        
        # Try to get status from inspection if available (for non-ghosts)
        status_str = ""
        if not self._is_ghost:
            try:
                # Get status from inspection without triggering full inspection
                raw_data = self._entity_ops.inspect_entity(self.name, self.position)
                status_value = raw_data.get("status")
                if status_value is not None:
                    try:
                        status_enum = EntityStatus(status_value)
                        status_str = f", status={status_enum.name}"
                    except (ValueError, TypeError):
                        pass
            except Exception:
                # If inspection fails, just skip status
                pass
        
        return f"{prefix}[{entity_name}]('{self.name}', ({pos.x}, {pos.y}){dir_str}{status_str})"
