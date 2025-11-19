"""Entity classes representing Factorio entities."""

from typing import Dict, Optional, Any
from abc import ABC

from FactoryVerse.observations import MapView
from FactoryVerse.infra.rcon_helper import RconHelper


class Entity(ABC):
    """Base entity - identified by position + name/type."""
    
    def __init__(
        self,
        position: Dict[str, float],
        name: str,
        entity_type: str,
        unit_number: Optional[int] = None,
        map_view: Optional[MapView] = None,
        helper: Optional[RconHelper] = None,
        agent_id: Optional[int] = None,
    ):
        """
        Initialize entity.
        
        Args:
            position: Position dict with 'x' and 'y' keys
            name: Entity prototype name
            entity_type: Entity type string
            unit_number: Unit number (if available, not for finding)
            map_view: MapView instance for queries
            helper: RconHelper instance for actions
            agent_id: Agent ID for actions
        """
        self.position = position
        self.name = name
        self.type = entity_type
        self.unit_number = unit_number
        self._map_view = map_view
        self._helper = helper
        self._agent_id = agent_id
    
    def __eq__(self, other):
        """Entities are equal if same position and name."""
        if not isinstance(other, Entity):
            return False
        return (
            self.position == other.position
            and self.name == other.name
        )
    
    def __hash__(self):
        """Hash based on position and name."""
        return hash((self.position['x'], self.position['y'], self.name))
    
    def __repr__(self):
        return f"{self.__class__.__name__}(name={self.name!r}, position=({self.position['x']:.1f}, {self.position['y']:.1f}))"


class Machine(Entity):
    """Base for machines that can have recipes."""
    pass


class Assembler(Machine):
    """Assembling machine."""
    pass


class ChemicalPlant(Machine):
    """Chemical plant."""
    pass


class Furnace(Entity):
    """Furnace entity."""
    pass


class MiningDrill(Entity):
    """Mining drill."""
    pass


class OffShorePump(Entity):
    """Offshore pump."""
    pass


class Belt(Entity):
    """Transport belt."""
    pass


class Pipe(Entity):
    """Pipe."""
    pass


# Resource types
class Resource(Entity):
    """Base for resources."""
    pass


class Ore(Resource):
    """Ore resource."""
    pass


class CrudeOil(Resource):
    """Crude oil resource."""
    pass


class Tree(Resource):
    """Tree resource."""
    pass


class SimpleEntity(Resource):
    """Rocks and other simple entities."""
    pass

