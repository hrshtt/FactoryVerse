--[[
    Factorio Entity Rotation Action

    This action allows an agent to rotate an entity in the game world, simulating the effect of a player pressing the 'R' key. 
    Rotating entities can be important for automation, logistics, and overall base layout optimization.

    Most entities in Factorio are rotatable, meaning their orientation can be changed after placement. This includes belts, inserters, underground belts, splitters, furnaces, and more. However, there are important exceptions:
      - Assemblers (assembling machines) are typically **not rotatable* (see: https://factorio-draftsman.readthedocs.io/en/latest/reference/prototypes/assembling_machine.html).
      - Turrets (including ammo turrets, laser turrets, etc.) are generally **not rotatable* (see: https://factorio-draftsman.readthedocs.io/en/latest/reference/prototypes/ammo_turret.html).
      - Any entity which has the **'not-rotatable' flag** in its prototype is explicitly prevented from being rotated, either before or after placement (see: https://lua-api.factorio.com/latest/concepts/EntityPrototypeFlag.html).
      - Some rectangular buildings or very specialized entities may only support flipping rather than rotation.
    Typically, the ability to rotate is determined by the entity's prototype configuration.

    This action should check for rotatability and gracefully handle attempts to rotate non-rotatable entities, e.g., by returning an error or a no-op.

    Input should include:
      - unit_number: unique identifier for the target entity
      - (Optionally) direction: If specified, rotate to a specific direction; otherwise, rotate to the next available direction.

    Useful for agent control, intelligent building, and world manipulation in agent-driven scenarios.
]]
