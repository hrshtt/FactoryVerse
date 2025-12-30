"""Mining drill entity implementations.

Mining drills extract resources from the ground.
Includes: ElectricMiningDrill, BurnerMiningDrill
"""

from typing import List, Optional, Dict
from FactoryVerse.factory.types import MapPosition, Direction
from FactoryVerse.factory.mixins import CrafterMixin, FuelableMixin
from FactoryVerse.factory.entity.base_entity import BaseEntity
from FactoryVerse.factory.entity.inspect import (
    MiningDrillInspection,
    MiningTargetData,
    BurnerData,
    EnergyData,
    EntityRef,
    BoundingBoxData,
)


def _parse_burner(data: Optional[Dict]) -> Optional[BurnerData]:
    """Parse burner data from Lua response."""
    if data is None:
        return None
    return BurnerData(
        heat=data.get("heat"),
        heat_capacity=data.get("heat_capacity"),
        remaining_burning_fuel=data.get("remaining_burning_fuel"),
        currently_burning=data.get("currently_burning"),
    )


def _parse_energy(data: Optional[Dict]) -> Optional[EnergyData]:
    """Parse energy data from Lua response."""
    if data is None:
        return None
    return EnergyData(
        current=data.get("current", 0),
        capacity=data.get("capacity", 0),
    )


def _parse_mining_target(data: Optional[Dict]) -> Optional[MiningTargetData]:
    """Parse mining target from Lua response."""
    if data is None:
        return None
    pos_data = data.get("position", {})
    return MiningTargetData(
        name=data.get("name", ""),
        type=data.get("type", ""),
        position=MapPosition(x=pos_data.get("x", 0), y=pos_data.get("y", 0)),
        amount=data.get("amount", 0),
    )


def _parse_entity_ref(data: Optional[Dict]) -> Optional[EntityRef]:
    """Parse entity reference from Lua response."""
    if data is None:
        return None
    pos_data = data.get("position", {})
    return EntityRef(
        name=data.get("name", ""),
        position=MapPosition(x=pos_data.get("x", 0), y=pos_data.get("y", 0)),
    )


def _parse_bounding_box(data: Optional[Dict]) -> Optional[BoundingBoxData]:
    """Parse bounding box from Lua response."""
    if data is None:
        return None
    left_top = data.get("left_top", {})
    right_bottom = data.get("right_bottom", {})
    return BoundingBoxData(
        left_top=MapPosition(x=left_top.get("x", 0), y=left_top.get("y", 0)),
        right_bottom=MapPosition(
            x=right_bottom.get("x", 0), y=right_bottom.get("y", 0)
        ),
    )


def _parse_position(data: Optional[Dict]) -> Optional[MapPosition]:
    """Parse position from Lua response."""
    if data is None:
        return None
    return MapPosition(x=data.get("x", 0), y=data.get("y", 0))


class ElectricMiningDrill(BaseEntity):
    """An electric mining drill entity.

    Direction is REQUIRED for mining drills as they have directional output positions.
    """

    def __init__(
        self,
        name: str,
        position: MapPosition,
        direction: Optional[Direction] = None,
        **kwargs,
    ):
        super().__init__(name, position, direction, **kwargs)
        if self.direction is None:
            raise ValueError(
                f"ElectricMiningDrill requires direction to be set. "
                f"Entity at ({position.x}, {position.y}) is missing direction data."
            )

    def _format_inspection(self, data: Dict) -> str:
        """Format electric mining drill inspection data.

        Args:
            data: Raw inspection data from Lua (matches inspect_mining_drill output)

        Returns:
            Formatted string for agent consumption
        """
        pos_data = data.get("position", {})
        position = MapPosition(x=pos_data.get("x", 0), y=pos_data.get("y", 0))

        inspection = MiningDrillInspection(
            entity_name=data.get("entity_name", ""),
            entity_type=data.get("entity_type", ""),
            position=position,
            direction=data.get("direction", 0),
            tick=data.get("tick", 0),
            health=data.get("health"),
            max_health=data.get("max_health"),
            status=data.get("status"),
            mining_target=_parse_mining_target(data.get("mining_target")),
            mining_progress=data.get("mining_progress"),
            bonus_mining_progress=data.get("bonus_mining_progress"),
            output=data.get("output"),  # Direct from Lua
            drop_position=_parse_position(data.get("drop_position")),
            drop_target=_parse_entity_ref(data.get("drop_target")),
            mining_area=_parse_bounding_box(data.get("mining_area")),
            energy=_parse_energy(data.get("energy")),
            burner=None,  # Electric drills don't have burners
            mining_drill_filter_mode=data.get("mining_drill_filter_mode"),
        )
        return str(inspection)


class BurnerMiningDrill(CrafterMixin, FuelableMixin, BaseEntity):
    """A burner mining drill entity.

    Direction is REQUIRED for mining drills as they have directional output positions.
    """

    def __init__(
        self,
        name: str,
        position: MapPosition,
        direction: Optional[Direction] = None,
        **kwargs,
    ):
        super().__init__(name, position, direction, **kwargs)
        if self.direction is None:
            raise ValueError(
                f"BurnerMiningDrill requires direction to be set. "
                f"Entity at ({position.x}, {position.y}) is missing direction data."
            )

    def _get_accepted_fuel_categories(self) -> List[str]:
        """Burner drills accept chemical fuel."""
        return ["chemical"]

    def _format_inspection(self, data: Dict) -> str:
        """Format burner mining drill inspection data.

        Args:
            data: Raw inspection data from Lua (matches inspect_mining_drill output)

        Returns:
            Formatted string for agent consumption
        """
        pos_data = data.get("position", {})
        position = MapPosition(x=pos_data.get("x", 0), y=pos_data.get("y", 0))

        inspection = MiningDrillInspection(
            entity_name=data.get("entity_name", ""),
            entity_type=data.get("entity_type", ""),
            position=position,
            direction=data.get("direction", 0),
            tick=data.get("tick", 0),
            health=data.get("health"),
            max_health=data.get("max_health"),
            status=data.get("status"),
            mining_target=_parse_mining_target(data.get("mining_target")),
            mining_progress=data.get("mining_progress"),
            bonus_mining_progress=data.get("bonus_mining_progress"),
            output=data.get("output"),  # Direct from Lua
            drop_position=_parse_position(data.get("drop_position")),
            drop_target=_parse_entity_ref(data.get("drop_target")),
            mining_area=_parse_bounding_box(data.get("mining_area")),
            energy=None,  # Burner drills don't use electricity
            burner=_parse_burner(data.get("burner")),
            mining_drill_filter_mode=data.get("mining_drill_filter_mode"),
        )
        return str(inspection)
