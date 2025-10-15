"""
FactoryVerse Actions - TODO: Implement

This module should provide direct Python functions for Factorio actions,
callable from agent notebooks.

Expected interface (based on factorio-verse.md):

    from FactoryVerse.actions import (
        move_to,
        place_entity,
        craft_item,
        harvest_resource,
        connect_entities,
        remove_entity,
        set_recipe,
        insert_items,
        extract_items,
    )

    # Usage in notebook:
    move_to(x=10, y=10)
    place_entity("burner-mining-drill", x=5, y=5)
    craft_item("iron-gear-wheel", count=10)
    harvest_resource(x=0, y=0, amount=50)

Implementation approach:
1. Wrap the existing RCON action system (remote.call("actions", ...))
2. Provide Pythonic types (Direction Enum)
3. Handle serialization/deserialization of Lua responses
4. Integrate with experiment context for RCON connection

See src/FactoryVerse/infra/rcon.py for RCON utilities.
See src/factorio/factorio_verse/actions/ for Lua action implementations.
"""

# TODO: Implement action wrappers
# For now, this module is a placeholder

__all__ = []
