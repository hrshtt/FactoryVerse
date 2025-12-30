"""Inserter entity implementations.

Inserters move items between entities (belts, machines, chests).
Includes: Inserter, FastInserter, LongHandInserter, BurnerInserter, FilterInserter, etc.
"""

from typing import Dict, List, Optional
from FactoryVerse.factory.types import MapPosition, Direction
from FactoryVerse.factory.mixins import FuelableMixin
from FactoryVerse.factory.entity.base_entity import BaseEntity
from FactoryVerse.factory.entity.inspect import (
    InserterInspection,
    BurnerData,
    EntityRef,
    HeldItemData,
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


def _parse_entity_ref(data: Optional[Dict]) -> Optional[EntityRef]:
    """Parse entity reference from Lua response."""
    if data is None:
        return None
    pos_data = data.get("position", {})
    return EntityRef(
        name=data.get("name", ""),
        position=MapPosition(x=pos_data.get("x", 0), y=pos_data.get("y", 0)),
    )


def _parse_position(data: Optional[Dict]) -> Optional[MapPosition]:
    """Parse position from Lua response."""
    if data is None:
        return None
    return MapPosition(x=data.get("x", 0), y=data.get("y", 0))


def _parse_held_item(data: Optional[Dict]) -> Optional[HeldItemData]:
    """Parse held item from Lua response."""
    if data is None:
        return None
    return HeldItemData(
        name=data.get("name", ""),
        count=data.get("count", 0),
    )


class Inserter(BaseEntity):
    """An inserter entity.

    **For Agents**: Inserters move items between entities. They pick up from one side
    and drop on the other. Use inspect() to see what they're holding and their targets.
    """

    def _format_inspection(self, data: Dict) -> str:
        """Format inserter inspection data.

        Args:
            data: Raw inspection data from Lua (matches inspect_inserter output)

        Returns:
            Formatted string for agent consumption
        """
        pos_data = data.get("position", {})
        position = MapPosition(x=pos_data.get("x", 0), y=pos_data.get("y", 0))

        inspection = InserterInspection(
            entity_name=data.get("entity_name", ""),
            entity_type=data.get("entity_type", ""),
            position=position,
            direction=data.get("direction", 0),
            tick=data.get("tick", 0),
            health=data.get("health"),
            max_health=data.get("max_health"),
            status=data.get("status"),
            held_item=_parse_held_item(data.get("held_item")),
            held_stack_position=_parse_position(data.get("held_stack_position")),
            pickup_position=_parse_position(data.get("pickup_position")),
            drop_position=_parse_position(data.get("drop_position")),
            pickup_target=_parse_entity_ref(data.get("pickup_target")),
            drop_target=_parse_entity_ref(data.get("drop_target")),
            inserter_filter_mode=data.get("inserter_filter_mode"),
            filter_slot_count=data.get("filter_slot_count"),
            filters=data.get("filters"),
            inserter_stack_size_override=data.get("inserter_stack_size_override"),
            inserter_target_pickup_count=data.get("inserter_target_pickup_count"),
            pickup_from_left_lane=data.get("pickup_from_left_lane"),
            pickup_from_right_lane=data.get("pickup_from_right_lane"),
            use_filters=data.get("use_filters"),
            burner=None,  # Regular inserters don't have burners
        )
        return str(inspection)

    @property
    def pickup_position(self) -> Optional[MapPosition]:
        """Get the inserter's pickup position.

        **For Agents**: This is where the inserter picks up items from.
        """
        # This would need to be calculated from direction and prototype
        # For now, return None - inspect() gives the actual runtime value
        return None

    @property
    def drop_position(self) -> Optional[MapPosition]:
        """Get the inserter's drop position.

        **For Agents**: This is where the inserter drops items to.
        """
        # This would need to be calculated from direction and prototype
        # For now, return None - inspect() gives the actual runtime value
        return None


class FastInserter(Inserter):
    """Fast inserter - faster movement speed."""

    pass


class LongHandedInserter(Inserter):
    """Long-handed inserter - extended reach."""

    pass


class FilterInserter(Inserter):
    """Filter inserter - can filter items."""

    pass


class StackInserter(Inserter):
    """Stack inserter - moves multiple items at once."""

    pass


class StackFilterInserter(Inserter):
    """Stack filter inserter - moves multiple items with filtering."""

    pass


class BulkInserter(Inserter):
    """Bulk inserter (2.0) - faster stack inserter."""

    pass


class BurnerInserter(FuelableMixin, Inserter):
    """Burner inserter - requires fuel to operate.

    **For Agents**: This inserter needs fuel (coal, wood, etc.) to function.
    Use add_fuel() to refuel it.
    """

    def _get_accepted_fuel_categories(self) -> List[str]:
        """Burner inserters accept chemical fuel."""
        return ["chemical"]

    def _format_inspection(self, data: Dict) -> str:
        """Format burner inserter inspection data."""
        pos_data = data.get("position", {})
        position = MapPosition(x=pos_data.get("x", 0), y=pos_data.get("y", 0))

        inspection = InserterInspection(
            entity_name=data.get("entity_name", ""),
            entity_type=data.get("entity_type", ""),
            position=position,
            direction=data.get("direction", 0),
            tick=data.get("tick", 0),
            health=data.get("health"),
            max_health=data.get("max_health"),
            status=data.get("status"),
            held_item=_parse_held_item(data.get("held_item")),
            held_stack_position=_parse_position(data.get("held_stack_position")),
            pickup_position=_parse_position(data.get("pickup_position")),
            drop_position=_parse_position(data.get("drop_position")),
            pickup_target=_parse_entity_ref(data.get("pickup_target")),
            drop_target=_parse_entity_ref(data.get("drop_target")),
            inserter_filter_mode=data.get("inserter_filter_mode"),
            filter_slot_count=data.get("filter_slot_count"),
            filters=data.get("filters"),
            inserter_stack_size_override=data.get("inserter_stack_size_override"),
            inserter_target_pickup_count=data.get("inserter_target_pickup_count"),
            pickup_from_left_lane=data.get("pickup_from_left_lane"),
            pickup_from_right_lane=data.get("pickup_from_right_lane"),
            use_filters=data.get("use_filters"),
            burner=_parse_burner(data.get("burner")),
        )
        return str(inspection)
