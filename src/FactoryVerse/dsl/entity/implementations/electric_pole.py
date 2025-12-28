"""Electric pole entity implementations.

Electric poles distribute electricity across the factory.
Includes: SmallElectricPole, MediumElectricPole, BigElectricPole, Substation
"""

from typing import Dict, Optional
from FactoryVerse.dsl.types import MapPosition, Direction
from FactoryVerse.dsl.entity.base_entity import BaseEntity
from FactoryVerse.dsl.entity.inspect import (
    ElectricPoleInspection,
    EnergyData,
)


def _parse_energy(data: Optional[Dict]) -> Optional[EnergyData]:
    """Parse energy data from Lua response."""
    if data is None:
        return None
    return EnergyData(
        current=data.get("current", 0),
        capacity=data.get("capacity", 0),
    )


class ElectricPole(BaseEntity):
    """An electric pole entity.

    **For Agents**: Electric poles connect to form a power network. They have a supply
    area where machines can draw power, and a wire reach defining connection distance.
    """

    def _format_inspection(self, data: Dict) -> str:
        """Format electric pole inspection data.

        Args:
            data: Raw inspection data from Lua (matches inspect_electric_pole output)

        Returns:
            Formatted string for agent consumption
        """
        pos_data = data.get("position", {})
        position = MapPosition(x=pos_data.get("x", 0), y=pos_data.get("y", 0))

        inspection = ElectricPoleInspection(
            entity_name=data.get("entity_name", ""),
            entity_type=data.get("entity_type", ""),
            position=position,
            direction=data.get("direction", 0),
            tick=data.get("tick", 0),
            health=data.get("health"),
            max_health=data.get("max_health"),
            status=data.get("status"),
            electric_network_id=data.get("electric_network_id"),
            is_connected=data.get("is_connected", False),
            energy=_parse_energy(data.get("energy")),
        )
        return str(inspection)


class SmallElectricPole(ElectricPole):
    """Small electric pole - basic, short range.

    Supply area: 5x5, Wire reach: 7.5 tiles
    """

    pass


class MediumElectricPole(ElectricPole):
    """Medium electric pole - larger supply area.

    Supply area: 7x7, Wire reach: 9 tiles
    """

    pass


class BigElectricPole(ElectricPole):
    """Big electric pole - long range connections.

    Supply area: 4x4, Wire reach: 30 tiles
    """

    pass


class Substation(ElectricPole):
    """Substation - largest supply area.

    Supply area: 18x18, Wire reach: 18 tiles
    """

    pass
