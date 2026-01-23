"""Rotatable capabilities - mixins for entities that can be rotated.

Provides RotatableMixin (90° rotation) and Rotatable180Mixin (180° toggle).
RotatableMixin owns the direction attribute - non-rotatable entities have no direction.
"""

from typing import Optional, TYPE_CHECKING
from FactoryVerse.game.factory.types import Direction

if TYPE_CHECKING:
    from FactoryVerse.game.agent.embodied_actions.entity_operations import EntityOperationsAction


class RotatableMixin:
    """Mixin for entities that can be rotated 90 degrees.

    **OWNS the direction attribute** - only rotatable entities have direction.
    Used by: inserters, belts, mining drills, assemblers, etc.

    Entities inheriting this mixin must call `super().__init__()` first,
    then set `self.direction = direction` in their own `__init__`.
    """

    direction: Direction  # This mixin owns direction
    _entity_ops: "EntityOperationsAction"

    def rotate(self, clockwise: bool = True) -> Direction:
        """Rotate entity 90 degrees.

        Args:
            clockwise: If True, rotate right. If False, rotate left.

        Returns:
            New direction after rotation
        """
        if self.direction is None:
            raise ValueError(f"{self.__class__.__name__} has no direction to rotate")

        if clockwise:
            new_dir = self.direction.turn_right()
        else:
            new_dir = self.direction.turn_left()

        # TODO: When entity_ops supports rotation, call it here
        self.direction = new_dir
        return self.direction


class Rotatable180Mixin:
    """Mixin for entities that can only be rotated 180 degrees.

    **OWNS the direction attribute** - only rotatable entities have direction.
    Used by: splitters (can only toggle between opposite directions)
    """

    direction: Direction  # This mixin owns direction

    def rotate_180(self) -> Direction:
        """Toggle between opposite directions (N↔S, E↔W).

        Returns:
            New direction after 180° rotation
        """
        if self.direction is None:
            raise ValueError(f"{self.__class__.__name__} has no direction to rotate")

        self.direction = self.direction.flip()
        return self.direction
