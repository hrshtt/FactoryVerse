"""Transport belt entity implementations.

Transport belts move items along conveyor paths.
Includes: TransportBelt, FastTransportBelt, ExpressTransportBelt,
          UndergroundBelt, Splitter, and their fast/express variants.
"""

from typing import Dict, List, Optional
from FactoryVerse.factory.types import MapPosition, Direction
from FactoryVerse.factory.entity.base_entity import BaseEntity
from FactoryVerse.factory.entity.inspect import (
    TransportBeltInspection,
    EntityRef,
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


def _parse_belt_neighbours(data: Optional[List]) -> Optional[List[EntityRef]]:
    """Parse belt neighbours list from Lua response."""
    if data is None:
        return None
    return [_parse_entity_ref(n) for n in data if n is not None]


class TransportBelt(BaseEntity):
    """A transport belt entity.

    **For Agents**: Transport belts move items in one direction. They have left and right
    lanes that can carry different items.
    """

    def _format_inspection(self, data: Dict) -> str:
        """Format transport belt inspection data.

        Args:
            data: Raw inspection data from Lua (matches inspect_transport_belt output)

        Returns:
            Formatted string for agent consumption
        """
        pos_data = data.get("position", {})
        position = MapPosition(x=pos_data.get("x", 0), y=pos_data.get("y", 0))

        inspection = TransportBeltInspection(
            entity_name=data.get("entity_name", ""),
            entity_type=data.get("entity_type", ""),
            position=position,
            direction=data.get("direction", 0),
            tick=data.get("tick", 0),
            health=data.get("health"),
            max_health=data.get("max_health"),
            status=data.get("status"),
            belt_shape=data.get("belt_shape"),
            belt_neighbours=_parse_belt_neighbours(data.get("belt_neighbours")),
            linked_belt_neighbour=_parse_entity_ref(data.get("linked_belt_neighbour")),
            linked_belt_type=data.get("linked_belt_type"),
            belt_to_ground_type=None,  # Not underground
            splitter_filter=None,
            splitter_input_priority=None,
            splitter_output_priority=None,
        )
        return str(inspection)


class FastTransportBelt(TransportBelt):
    """Fast transport belt - 2x speed of regular belt."""

    pass


class ExpressTransportBelt(TransportBelt):
    """Express transport belt - 3x speed of regular belt."""

    pass


class UndergroundBelt(BaseEntity):
    """An underground belt entity.

    **For Agents**: Underground belts go underground to pass under obstacles.
    They come in pairs (input/output).
    """

    def _format_inspection(self, data: Dict) -> str:
        """Format underground belt inspection data."""
        pos_data = data.get("position", {})
        position = MapPosition(x=pos_data.get("x", 0), y=pos_data.get("y", 0))

        inspection = TransportBeltInspection(
            entity_name=data.get("entity_name", ""),
            entity_type=data.get("entity_type", ""),
            position=position,
            direction=data.get("direction", 0),
            tick=data.get("tick", 0),
            health=data.get("health"),
            max_health=data.get("max_health"),
            status=data.get("status"),
            belt_shape=None,
            belt_neighbours=_parse_belt_neighbours(data.get("belt_neighbours")),
            linked_belt_neighbour=_parse_entity_ref(data.get("linked_belt_neighbour")),
            linked_belt_type=data.get("linked_belt_type"),
            belt_to_ground_type=data.get("belt_to_ground_type"),
            splitter_filter=None,
            splitter_input_priority=None,
            splitter_output_priority=None,
        )
        return str(inspection)


class FastUndergroundBelt(UndergroundBelt):
    """Fast underground belt - matches fast belt speed."""

    pass


class ExpressUndergroundBelt(UndergroundBelt):
    """Express underground belt - matches express belt speed."""

    pass


class Splitter(BaseEntity):
    """A splitter entity.

    **For Agents**: Splitters split belt contents between two output lanes.
    Can be configured with input/output priority and item filters.
    """

    def _format_inspection(self, data: Dict) -> str:
        """Format splitter inspection data."""
        pos_data = data.get("position", {})
        position = MapPosition(x=pos_data.get("x", 0), y=pos_data.get("y", 0))

        inspection = TransportBeltInspection(
            entity_name=data.get("entity_name", ""),
            entity_type=data.get("entity_type", ""),
            position=position,
            direction=data.get("direction", 0),
            tick=data.get("tick", 0),
            health=data.get("health"),
            max_health=data.get("max_health"),
            status=data.get("status"),
            belt_shape=None,
            belt_neighbours=_parse_belt_neighbours(data.get("belt_neighbours")),
            linked_belt_neighbour=None,
            linked_belt_type=None,
            belt_to_ground_type=None,
            splitter_filter=data.get("splitter_filter"),
            splitter_input_priority=data.get("splitter_input_priority"),
            splitter_output_priority=data.get("splitter_output_priority"),
        )
        return str(inspection)


class FastSplitter(Splitter):
    """Fast splitter - matches fast belt speed."""

    pass


class ExpressSplitter(Splitter):
    """Express splitter - matches express belt speed."""

    pass


class Loader(BaseEntity):
    """A loader entity.

    **For Agents**: Loaders quickly load/unload items between belts and containers.
    """

    def _format_inspection(self, data: Dict) -> str:
        """Format loader inspection data."""
        pos_data = data.get("position", {})
        position = MapPosition(x=pos_data.get("x", 0), y=pos_data.get("y", 0))

        # Loaders use transport belt inspection as base
        inspection = TransportBeltInspection(
            entity_name=data.get("entity_name", ""),
            entity_type=data.get("entity_type", ""),
            position=position,
            direction=data.get("direction", 0),
            tick=data.get("tick", 0),
            health=data.get("health"),
            max_health=data.get("max_health"),
            status=data.get("status"),
            belt_shape=None,
            belt_neighbours=None,
            linked_belt_neighbour=None,
            linked_belt_type=None,
            belt_to_ground_type=None,
            splitter_filter=None,
            splitter_input_priority=None,
            splitter_output_priority=None,
        )
        return str(inspection)


class FastLoader(Loader):
    """Fast loader - matches fast belt speed."""

    pass


class ExpressLoader(Loader):
    """Express loader - matches express belt speed."""

    pass
