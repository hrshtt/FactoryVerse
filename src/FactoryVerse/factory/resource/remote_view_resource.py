"""Resource view wrapper for category-based access control.

This module provides a thin wrapper around resource instances to enforce
access restrictions based on how the resource was obtained:

- RemoteViewResource: Database queries (read-only, no mining)
- ReachableResource: Direct access via reachable_resources (full interface including mine())

The wrapper approach is simple:
1. Delegate all attribute access to wrapped resource
2. Block mine() method with clear error message
3. Self-documenting type representation

This gives LLMs clear documentation:
- What you CAN do is visible via delegation (inspect, properties)
- What you CAN'T do raises AttributeError with helpful message (mine)
"""

from typing import Optional, List, Dict, Any, Union

# Mutation methods that should NOT exist on read-only resource views
_READ_ONLY_BLOCKED_METHODS = {
    'mine',  # Can't mine remote resources
}


class RemoteViewResource:
    """Read-only resource wrapper for database query results.
    
    RemoteViewResource represents resources queried from the map database.
    You can inspect and plan with them, but cannot mine them.
    
    To mine a RemoteViewResource:
    1. Navigate to its position
    2. Get it as reachable: reachable_resources.get_resource(name, position)
    3. Now you can mine()
    
    Example:
        >>> # Query resource from database
        >>> patches = map_db.get_resources('''
        ...     SELECT * FROM resource_patch
        ...     WHERE resource_name = 'iron-ore'
        ... ''')
        >>> patch = patches[0]
        >>> type(patch)
        <class 'RemoteViewResource'>
        >>> patch.position  # ✓ Properties work
        MapPosition(x=50.0, y=50.0)
        >>> patch.total  # ✓ Properties work
        5000
        >>> patch.inspect()  # ✓ Inspection works
        'ResourceOrePatch(iron-ore) at (50.0, 50.0)...'
        >>> patch.mine()  # ✗ Mining blocked
        AttributeError: 'RemoteViewResource' does not support 'mine' (read-only view)
    """
    
    def __init__(self, resource):
        """Wrap a resource for read-only access.
        
        Args:
            resource: The underlying resource instance (BaseResource or ResourceOrePatch)
        """
        self._resource = resource
    
    def __repr__(self) -> str:
        """Self-documenting representation showing category and type."""
        resource_class = self._resource.__class__.__name__
        name = self._resource.name
        pos = self._resource.position
        
        return f"RemoteViewResource[{resource_class}](name='{name}', position=({pos.x}, {pos.y}))"
    
    def __getattr__(self, name):
        """Delegate attribute access with mutation blocking.
        
        This allows:
        - All spatial properties (position, amount, total, count)
        - inspect() method
        - All other read-only methods
        
        This blocks:
        - mine() method
        """
        # Block mine() method
        if name in _READ_ONLY_BLOCKED_METHODS:
            raise AttributeError(
                f"'RemoteViewResource' does not support '{name}' (read-only view). "
                f"To mine this resource, navigate to it and use reachable_resources.get_resource()."
            )
        
        # Delegate everything else to wrapped resource
        return getattr(self._resource, name)


__all__ = ['RemoteViewResource']
