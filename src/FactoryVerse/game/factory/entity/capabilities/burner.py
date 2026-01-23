"""Burner capability - state and mixin for fuel-burning entities.

Co-locates BurnerState (Pydantic model) and BurnerMixin for entities
that burn fuel like furnaces, burner drills, burner inserters, boilers.
"""

from typing import Optional, List, Dict, TYPE_CHECKING
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from FactoryVerse.game.factory.item.base import ItemStack
    from FactoryVerse.game.agent.embodied_actions.entity_operations import (
        EntityOperationsAction,
    )


class BurnerState(BaseModel):
    """State for burner-powered entities.

    Source: runtime_inspection.jsonl burner object
    """

    heat: float = 0
    heat_capacity: float = 0
    remaining_burning_fuel: float = 0
    currently_burning: Optional[str] = None
    fuel_inventory: Dict[str, int] = Field(default_factory=dict)  # item_name -> count


class BurnerMixin:
    """Mixin for entities that burn fuel for energy.

    Provides:
    - _get_burner_state() for inspection
    - add_fuel() for fueling the entity

    Requires entity to have:
    - is_ghost: bool
    - _entity_ops: EntityOperationsAction (injected)
    - name: str
    - position: Position
    """

    # Type hints for required attributes (provided by BaseEntity)
    is_ghost: bool
    _entity_ops: "EntityOperationsAction"
    name: str

    def _get_burner_state(self, inspection_data: dict) -> BurnerState:
        """Get burner state from inspection data.

        Args:
            inspection_data: Raw inspection data from Lua

        Returns:
            BurnerState populated from inspection data
        """
        if self.is_ghost:
            return BurnerState()  # Ghosts have no burner data

        # Use transformer to handle Lua quirks (nested inventory structure, etc.)
        from FactoryVerse.game.factory.entity.transform import _transform_burner

        burner_state = _transform_burner(inspection_data)
        return burner_state if burner_state else BurnerState()

    def _get_accepted_fuel_categories(self) -> List[str]:
        """Return accepted fuel categories for this entity.

        Override in subclasses to specify fuel types.
        Default: chemical fuel only.
        """
        return ["chemical"]

    def add_fuel(self, items: List["ItemStack"]) -> List:
        """Add fuel to the entity.

        **For Agents**: Use this to fuel burner entities (furnaces, drills, etc.)

        Args:
            items: List of ItemStack containing fuel items

        Returns:
            List of results from fuel addition
        """
        from FactoryVerse.game.factory.prototypes import get_item_prototypes

        results = []
        for item in items:
            # Validate fuel type
            item_protos = get_item_prototypes()
            if not item_protos.is_fuel(item.name):
                valid_fuels = item_protos.get_fuel_items()
                raise ValueError(
                    f"Cannot add '{item.name}' as fuel to {self.name}. "
                    f"Valid fuel items: {', '.join(sorted(valid_fuels))}"
                )

            fuel_category = item_protos.get_fuel_category(item.name)
            accepted = self._get_accepted_fuel_categories()
            if fuel_category not in accepted:
                raise ValueError(
                    f"Cannot add '{item.name}' (category={fuel_category}). "
                    f"Accepted: {', '.join(accepted)}"
                )

            result = self._entity_ops.put_inventory_item(
                self.name,
                "fuel",
                item,
                self.position,  # type: ignore
            )
            results.append(result)
        return results

    def take_fuel(self, item_name: Optional[str] = None, count: int = 1) -> List:
        """Take fuel from the entity.

        **For Agents**: Use this to retrieve fuel from burner entities.

        Args:
            item_name: Optional specific fuel item to take. If None, takes any fuel.
            count: Number of items to take (default 1)

        Returns:
            List of taken items
        """
        result = self._entity_ops.take_inventory_item(
            self.name,
            "fuel",
            item_name or "",  # Empty string = any
            count,
            self.position,  # type: ignore
        )
        return result.to_item_stacks(self._place_ops)
