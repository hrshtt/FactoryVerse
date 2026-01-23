"""Inserter entity implementations.

Inserters move items between entities (belts, machines, chests).
"""

from typing import List
from FactoryVerse.game.factory.entity.base_entity import BaseEntity
from FactoryVerse.game.factory.entity.capabilities import (
    BurnerMixin,
    ElectricMixin,
    InserterMixin,
    RotatableMixin,
)


class Inserter(InserterMixin, ElectricMixin, RotatableMixin, BaseEntity):
    """Electric inserter - moves items using electricity.

    **For Agents**: Inserters pick from one side and drop on the other.
    Use inspect() to see pickup_target and drop_target.
    """

    pass


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


class BurnerInserter(InserterMixin, BurnerMixin, RotatableMixin, BaseEntity):
    """Burner inserter - requires fuel to operate.

    **For Agents**: Use add_fuel() to refuel this inserter.
    """

    def _get_accepted_fuel_categories(self) -> List[str]:
        """Burner inserters accept chemical fuel."""
        return ["chemical"]
