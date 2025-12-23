"""Entity view wrappers for category-based access control.

This module provides thin wrappers around entity instances to enforce
access restrictions based on how the entity was obtained:

- RemoteViewEntity: Database queries (read-only)
- GhostEntity: Ghost placements (build/remove only)
- ReachableEntity: Direct access (full interface)

The wrapper approach is simple:
1. Delegate all attribute access to wrapped entity
2. Block mutation methods with clear error messages
3. Self-documenting type representation

This gives LLMs clear documentation:
- What you CAN do is visible via delegation
- What you CAN'T do raises AttributeError with helpful message
"""

from typing import Optional

# Mutation methods that should NOT exist on read-only views
_READ_ONLY_BLOCKED_METHODS = {
    'pickup',           # Can't pickup remote entities
    'add_fuel',         # Can't add fuel remotely
    'store_items',      # Can't store items remotely
    'take_items',       # Can't take items remotely
    'add_ingredients',  # Can't add ingredients remotely
    'take_products',    # Can't take products remotely
    'set_recipe',       # Can't set recipe remotely
    'build',            # Not a ghost
    'remove',           # Not a ghost
}

# Methods that should NOT exist on ghosts
_GHOST_BLOCKED_METHODS = {
    'pickup',           # Can't pickup ghosts
    'add_fuel',         # Ghosts don't consume fuel
    'store_items',      # Ghosts don't have inventory
    'take_items',       # Ghosts don't have inventory
    'add_ingredients',  # Ghosts don't process materials
    'take_products',    # Ghosts don't produce items
    'set_recipe',       # Ghosts don't craft
}


class RemoteViewEntity:
    """Read-only entity wrapper for database query results.
    
    RemoteViewEntity represents entities queried from the map database.
    You can inspect and plan with them, but cannot mutate them.
    
    To interact with a RemoteViewEntity:
    1. Navigate to its position
    2. Get it as reachable: reachable.get_entity(name, position)
    3. Now you have full access
    
    Example:
        >>> drill = map_db.get_entity("SELECT * FROM map_entity WHERE entity_name = 'burner-mining-drill' LIMIT 1")
        >>> type(drill)
        <class 'RemoteViewEntity'>
        >>> drill.output_position  # ✓ Planning works
        MapPosition(x=5.0, y=-1.5)
        >>> drill.pickup()  # ✗ Mutation blocked
        AttributeError: 'RemoteViewEntity' does not support 'pickup' (read-only view)
    """
    
    def __init__(self, entity):
        """Wrap an entity for read-only access.
        
        Args:
            entity: The underlying entity instance
        """
        self._entity = entity
    
    def __repr__(self) -> str:
        """Self-documenting representation showing category and type."""
        entity_class = self._entity.__class__.__name__
        pos = self._entity.position
        
        if self._entity.direction is not None:
            return f"RemoteViewEntity[{entity_class}](name='{self._entity.name}', position=({pos.x}, {pos.y}), direction={self._entity.direction.name})"
        else:
            return f"RemoteViewEntity[{entity_class}](name='{self._entity.name}', position=({pos.x}, {pos.y}))"
    
    def __getattr__(self, name):
        """Delegate attribute access with mutation blocking.
        
        This allows:
        - All spatial properties (position, tile_width, etc.)
        - All prototype data
        - inspect() method
        - Entity-specific planning (output_position for drills)
        
        This blocks:
        - All mutation methods (pickup, add_fuel, etc.)
        """
        # Block mutation methods
        if name in _READ_ONLY_BLOCKED_METHODS:
            raise AttributeError(
                f"'RemoteViewEntity' does not support '{name}' (read-only view). "
                f"To mutate this entity, navigate to it and use reachable.get_entity()."
            )
        
        # Delegate everything else to wrapped entity
        return getattr(self._entity, name)


class GhostEntity:
    """Ghost entity wrapper for planned placements.
    
    GhostEntity represents planned entities that can be built.
    You can inspect, plan, build, or remove them, but cannot mutate their state.
    
    Example:
        >>> ghost = item.place_ghost(position, direction=Direction.NORTH)
        >>> type(ghost)
        <class 'GhostEntity'>
        >>> ghost.output_position  # ✓ Planning works
        MapPosition(x=5.0, y=-1.5)
        >>> ghost.build()  # ✓ Build works
        >>> ghost.add_fuel(coal)  # ✗ Ghosts don't consume fuel
        AttributeError: 'GhostEntity' does not support 'add_fuel' (not yet built)
    """
    
    def __init__(self, entity):
        """Wrap an entity as a ghost.
        
        Args:
            entity: The underlying ghost entity instance
        """
        self._entity = entity
    
    def __repr__(self) -> str:
        """Self-documenting representation showing this is a ghost."""
        entity_class = self._entity.__class__.__name__
        pos = self._entity.position
        
        if self._entity.direction is not None:
            return f"GhostEntity[{entity_class}](name='{self._entity.name}', position=({pos.x}, {pos.y}), direction={self._entity.direction.name})"
        else:
            return f"GhostEntity[{entity_class}](name='{self._entity.name}', position=({pos.x}, {pos.y}))"
    
    def __getattr__(self, name):
        """Delegate attribute access with mutation blocking.
        
        This allows:
        - All spatial properties
        - All prototype data
        - inspect() method
        - build() and remove() methods
        - Entity-specific planning (output_position for drills)
        
        This blocks:
        - All mutation methods (pickup, add_fuel, etc.)
        """
        # Block mutation methods
        if name in _GHOST_BLOCKED_METHODS:
            raise AttributeError(
                f"'GhostEntity' does not support '{name}' (not yet built). "
                f"Call ghost.build() first to create a real entity."
            )
        
        # Delegate everything else to wrapped entity
        return getattr(self._entity, name)


__all__ = ['RemoteViewEntity', 'GhostEntity']
