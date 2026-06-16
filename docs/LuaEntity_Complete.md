# LuaEntity
The primary interface for interacting with entities through the Lua API. Entities are everything that exists on the map except for tiles (see [LuaTile](runtime:LuaTile)).

Most functions on LuaEntity also work when the entity is contained in a ghost.

**Parent:** LuaControl

## Properties
### `absorbed_pollution`
- **Type:** `Any` (R)
- **Description:** 
- **Restriction:** Can only be used if this is: **Spawner**

### `active`
- **Type:** `Any` (R)
- **Description:** Deactivating an entity will stop all its operations (car will stop moving, inserters will stop working, fish will stop moving etc).  Reading from this returns `false` if the entity is deactivated in at least one of the following ways: [by script](runtime:LuaEntity::disabled_by_script), [by circuit network](runtime:LuaEntity::disabled_by_control_behavior), [by recipe](runtime:LuaEntity::disabled_by_recipe), [by freezing](runtime:LuaEntity::frozen), or by deconstruction.  Writing to this is deprecated and affects only the [disabled_by_script](runtime:LuaEntity::disabled_by_script) state.  Entities that are not active naturally can't be set to be active (setting it to be active will do nothing). Some entities (Corpse, FireFlame, Roboport, RollingStock, dying entities) need to remain active and will ignore writes.

### `ai_settings`
- **Type:** `Any` (R)
- **Description:** The ai settings of this unit.
- **Restriction:** Can only be used if this is: **Unit, SpiderUnit**

### `alert_parameters`
- **Type:** `Any` (R)
- **Description:** 
- **Restriction:** Can only be used if this is: **ProgrammableSpeaker**

### `allow_dispatching_robots`
- **Type:** `Any` (R)
- **Description:** Whether this character's personal roboports are allowed to dispatch robots.
- **Restriction:** Can only be used if this is: **Character**

### `always_on`
- **Type:** `Any` (R)
- **Description:** If the lamp is always on when not driven by control behavior.
- **Restriction:** Can only be used if this is: **Lamp**

### `amount`
- **Type:** `Any` (R)
- **Description:** Count of resource units contained.
- **Restriction:** Can only be used if this is: **ResourceEntity**

### `armed`
- **Type:** `Any` (R)
- **Description:** Whether this land mine is armed.
- **Restriction:** Can only be used if this is: **LandMine**

### `artillery_auto_targeting`
- **Type:** `Any` (R)
- **Description:** If this artillery auto-targets enemies.
- **Restriction:** Can only be used if this is: **ArtilleryWagon, ArtilleryTurret**

### `associated_player`
- **Type:** `Any` (R)
- **Description:** The player this character is associated with, if any. Set to `nil` to clear.  The player will be automatically disassociated when a controller is set on the character. Also, all characters associated to a player will be logged off when the player logs off in multiplayer.  A character associated with a player is not directly controlled by any player.
- **Restriction:** Can only be used if this is: **Character**

### `attached_cargo_pod`
- **Type:** `Any` (R)
- **Description:** The cargo pod attached to this rocket silo rocket if any.
- **Restriction:** Can only be used if this is: **RocketSiloRocket**

### `autopilot_destination`
- **Type:** `Any` (R)
- **Description:** Destination of this spidertron's autopilot, if any. Writing `nil` clears all destinations.
- **Restriction:** Can only be used if this is: **SpiderVehicle**

### `autopilot_destinations`
- **Type:** `Any` (R)
- **Description:** The queued destination positions of spidertron's autopilot.
- **Restriction:** Can only be used if this is: **SpiderVehicle**

### `backer_name`
- **Type:** `Any` (R)
- **Description:** The backer name assigned to this entity. Entities that support backer names are labs, locomotives, radars, roboports, and train stops. `nil` if this entity doesn't support backer names.  While train stops get the name of a backer when placed down, players can rename them if they want to. In this case, `backer_name` returns the player-given name of the entity.

### `base_damage_modifiers`
- **Type:** `Any` (R)
- **Description:** 
- **Restriction:** Can only be used if this is: **Projectile**

### `beacons_count`
- **Type:** `Any` (R)
- **Description:** Number of beacons affecting this effect receiver. Can only be used when the entity has an effect receiver (AssemblingMachine, Furnace, Lab, MiningDrills)

### `belt_neighbours`
- **Type:** `Any` (R)
- **Description:** The belt connectable neighbours of this belt connectable entity. Only entities that input to or are outputs of this entity. Does not contain the other end of an underground belt, see [LuaEntity::neighbours](runtime:LuaEntity::neighbours) for that.
- **Restriction:** Can only be used if this is: **TransportBeltConnectable**

### `belt_shape`
- **Type:** `Any` (R)
- **Description:** Gives what is the current shape of a transport-belt.
- **Restriction:** Can only be used if this is: **TransportBelt**

### `belt_to_ground_type`
- **Type:** `Any` (R)
- **Description:** Whether this underground belt goes into or out of the ground.
- **Restriction:** Can only be used if this is: **UndergroundBelt**

### `bonus_damage_modifiers`
- **Type:** `Any` (R)
- **Description:** 
- **Restriction:** Can only be used if this is: **Projectile**

### `bonus_mining_progress`
- **Type:** `Any` (R)
- **Description:** The bonus mining progress for this mining drill. Read yields a number in range [0, mining_target.prototype.mineable_properties.mining_time]. `nil` if this isn't a mining drill.

### `bonus_progress`
- **Type:** `Any` (R)
- **Description:** The current productivity bonus progress, as a number in range `[0, 1]`.
- **Restriction:** Can only be used if this is: **CraftingMachine**

### `bounding_box`
- **Type:** `Any` (R)
- **Description:** [LuaEntityPrototype::collision_box](runtime:LuaEntityPrototype::collision_box) around entity's given position and respecting the current entity orientation.

### `burner`
- **Type:** `Any` (R)
- **Description:** The burner energy source for this entity, if any.

### `cargo_bay_connection_owner`
- **Type:** `Any` (R)
- **Description:** The space platform hub or cargo landing pad this cargo bay is connected to if any.
- **Restriction:** Can only be used if this is: **CargoBay**

### `cargo_hatches`
- **Type:** `Any` (R)
- **Description:** The cargo hatches owned by this entity if any.

### `cargo_pod_destination`
- **Type:** `Any` (R)
- **Description:** The destination of this cargo pod entity.  Use [force_finish_ascending](runtime:LuaEntity::force_finish_ascending) if you want it to only descend from orbit.
- **Restriction:** Can only be used if this is: **CargoPod**

### `cargo_pod_origin`
- **Type:** `Any` (R)
- **Description:** The origin of this cargo pod entity. (Must be a silo, hub or pad)
- **Restriction:** Can only be used if this is: **CargoPod**

### `cargo_pod_state`
- **Type:** `Any` (R)
- **Description:** The state of this cargo pod entity.
- **Restriction:** Can only be used if this is: **CargoPod**

### `chain_signal_state`
- **Type:** `Any` (R)
- **Description:** The state of this chain signal.
- **Restriction:** Can only be used if this is: **RailChainSignal**

### `character_corpse_death_cause`
- **Type:** `Any` (R)
- **Description:** The reason this character corpse character died. `""` if there is no reason.
- **Restriction:** Can only be used if this is: **CharacterCorpse**

### `character_corpse_player_index`
- **Type:** `Any` (R)
- **Description:** The player index associated with this character corpse.  The index is not guaranteed to be valid so it should always be checked first if a player with that index actually exists.
- **Restriction:** Can only be used if this is: **CharacterCorpse**

### `character_corpse_tick_of_death`
- **Type:** `Any` (R)
- **Description:** The tick this character corpse died at.
- **Restriction:** Can only be used if this is: **CharacterCorpse**

### `cliff_orientation`
- **Type:** `Any` (R)
- **Description:** The orientation of this cliff.
- **Restriction:** Can only be used if this is: **Cliff**

### `color`
- **Type:** `Any` (R)
- **Description:** The color of this character, rolling stock, corpse, character corpse, train stop, simple-entity-with-owner, car, spider-vehicle, or lamp. `nil` if this entity doesn't use custom colors.  Car color is overridden by the color of the current driver/passenger, if there is one.

### `combat_robot_owner`
- **Type:** `Any` (R)
- **Description:** The owner of this combat robot, if any.
- **Restriction:** Can only be used if this is: **CombatRobot**

### `combinator_description`
- **Type:** `Any` (R)
- **Description:** The description on this combinator.
- **Restriction:** Can only be used if this is: **ArithmeticCombinator, DeciderCombinator, SelectorCombinator, ConstantCombinator**

### `commandable`
- **Type:** `Any` (R)
- **Description:** Returns a LuaCommandable for this entity or nil if entity is not commandable. Units and SpiderUnits are commandable.

### `connected_rail`
- **Type:** `Any` (R)
- **Description:** The rail entity this train stop is connected to, if any.
- **Restriction:** Can only be used if this is: **TrainStop**

### `connected_rail_direction`
- **Type:** `Any` (R)
- **Description:** Rail direction to which this train stop is binding. This returns a value even when no rails are present.
- **Restriction:** Can only be used if this is: **TrainStop**

### `consumption_bonus`
- **Type:** `Any` (R)
- **Description:** The consumption bonus of this entity.

### `consumption_modifier`
- **Type:** `Any` (R)
- **Description:** Multiplies the energy consumption.
- **Restriction:** Can only be used if this is: **Car**

### `copy_color_from_train_stop`
- **Type:** `Any` (R)
- **Description:** If this rolling stock has 'copy color from train stop' enabled.
- **Restriction:** Can only be used if this is: **RollingStock**

### `corpse_expires`
- **Type:** `Any` (R)
- **Description:** Whether this corpse will ever fade away.
- **Restriction:** Can only be used if this is: **Corpse**

### `corpse_immune_to_entity_placement`
- **Type:** `Any` (R)
- **Description:** If true, corpse won't be destroyed when entities are placed over it. If false, whether corpse will be removed or not depends on value of [CorpsePrototype::remove_on_entity_placement](prototype:CorpsePrototype::remove_on_entity_placement).
- **Restriction:** Can only be used if this is: **Corpse**

### `crafting_progress`
- **Type:** `Any` (R)
- **Description:** The current crafting progress, as a number in range `[0, 1]`.
- **Restriction:** Can only be used if this is: **CraftingMachine**

### `crafting_speed`
- **Type:** `Any` (R)
- **Description:** The current crafting speed, including speed bonuses from modules and beacons.
- **Restriction:** Can only be used if this is: **CraftingMachine, Character**

### `crane_destination`
- **Type:** `Any` (R)
- **Description:** Destination of the crane of this entity. Throws when trying to set the destination out of range.
- **Restriction:** Can only be used if this is: **AgriculturalTower**

### `crane_destination_3d`
- **Type:** `Any` (R)
- **Description:** Destination of the crane of this entity in 3D. Throws when trying to set the destination out of range.
- **Restriction:** Can only be used if this is: **AgriculturalTower**

### `crane_end_position_3d`
- **Type:** `Any` (R)
- **Description:** Returns current position in 3D for the end of the crane of this entity.
- **Restriction:** Can only be used if this is: **AgriculturalTower**

### `crane_grappler_destination`
- **Type:** `Any` (R)
- **Description:** Will set destination for the grappler of crane of this entity. The crane grappler will start moving to reach the destination, but the rest of the arm will remain stationary. Throws when trying to set the destination out of range.
- **Restriction:** Can only be used if this is: **AgriculturalTower**

### `crane_grappler_destination_3d`
- **Type:** `Any` (R)
- **Description:** Will set destination in 3D for the grappler of crane of this entity. The crane grappler will start moving to reach the destination, but the rest of the arm will remain stationary. Throws when trying to set the destination out of range.
- **Restriction:** Can only be used if this is: **AgriculturalTower**

### `created_by_corpse`
- **Type:** `Any` (R)
- **Description:** The corpse that caused this entity ghost to be created, if any.
- **Restriction:** Can only be used if this is: **EntityGhost**

### `custom_status`
- **Type:** `Any` (R)
- **Description:** A custom status for this entity that will be displayed in the GUI.

### `damage_dealt`
- **Type:** `Any` (R)
- **Description:** The damage dealt by this turret, artillery turret, or artillery wagon.
- **Restriction:** Can only be used if this is: **Turret**

### `destructible`
- **Type:** `Any` (R)
- **Description:** If set to `false`, this entity can't be damaged and won't be attacked automatically. It can however still be mined.  Entities that are indestructible naturally (they have no health, like smoke, resource etc) can't be set to be destructible.

### `direction`
- **Type:** `Any` (R)
- **Description:** The current direction this entity is facing.

### `disabled_by_control_behavior`
- **Type:** `Any` (R)
- **Description:** If the updatable entity is disabled by control behavior.  Always returns `false` if this entity is not considered [updatable](runtime:LuaEntity::is_updatable).
- **Restriction:** Can only be used if this is: **UpdatableEntity**

### `disabled_by_recipe`
- **Type:** `Any` (R)
- **Description:** If the assembling machine is disabled by recipe, e.g. due to [AssemblingMachinePrototype::disabled_when_recipe_not_researched](prototype:AssemblingMachinePrototype::disabled_when_recipe_not_researched).  Always returns `false` if this entity is not considered [updatable](runtime:LuaEntity::is_updatable).
- **Restriction:** Can only be used if this is: **UpdatableEntity**

### `disabled_by_script`
- **Type:** `Any` (R)
- **Description:** If the updatable entity is disabled by script.  Note: Some entities (Corpse, FireFlame, Roboport, RollingStock, dying entities) need to remain active and will ignore writes.  If this entity is not considered [updatable](runtime:LuaEntity::is_updatable) then this always returns `false` and writes will be ignored.
- **Restriction:** Can only be used if this is: **UpdatableEntity**

### `display_panel_always_show`
- **Type:** `Any` (R)
- **Description:** 
- **Restriction:** Can only be used if this is: **DisplayPanel**

### `display_panel_icon`
- **Type:** `Any` (R)
- **Description:** Icon visible on the display panel. Can be written only when it is not set by control behavior.
- **Restriction:** Can only be used if this is: **DisplayPanel**

### `display_panel_show_in_chart`
- **Type:** `Any` (R)
- **Description:** 
- **Restriction:** Can only be used if this is: **DisplayPanel**

### `display_panel_text`
- **Type:** `Any` (R)
- **Description:** Text visible on the display panel. Can be written only when it is not set by control behavior.
- **Restriction:** Can only be used if this is: **DisplayPanel**

### `draw_data`
- **Type:** `Any` (R)
- **Description:** Gives a draw data of the given entity if it supports such data.
- **Restriction:** Can only be used if this is: **RollingStock**

### `driver_is_gunner`
- **Type:** `Any` (R)
- **Description:** Whether the driver of this car or spidertron is the gunner. If `false`, the passenger is the gunner. `nil` if this is neither a car or a spidertron.
- **Restriction:** Can only be used if this is: **Car, SpiderVehicle**

### `drop_position`
- **Type:** `Any` (R)
- **Description:** Position where the entity puts its stuff.  Mining drills and crafting machines can't have their drop position changed; inserters must have `allow_custom_vectors` set to true on their prototype to allow changing the drop position.  Meaningful only for entities that put stuff somewhere, such as mining drills, crafting machines with a drop target or inserters.

### `drop_target`
- **Type:** `Any` (R)
- **Description:** The entity this entity is putting its items to. If there are multiple possible entities at the drop-off point, writing to this attribute allows a mod to choose which one to drop off items to. The entity needs to collide with the tile box under the drop-off position. `nil` if there is no entity to put items to, or if this is not an entity that puts items somewhere.

### `effective_speed`
- **Type:** `Any` (R)
- **Description:** The current speed of this unit in tiles per tick, taking into account any walking speed modifier given by the tile the unit is standing on. `nil` if this is not a unit.
- **Restriction:** Can only be used if this is: **Unit**

### `effectivity_modifier`
- **Type:** `Any` (R)
- **Description:** Multiplies the acceleration the car can create for one unit of energy. Defaults to `1`.
- **Restriction:** Can only be used if this is: **Car**

### `effects`
- **Type:** `Any` (R)
- **Description:** The effects being applied to this entity, if any. For beacons, this is the effect the beacon is broadcasting.

### `electric_buffer_size`
- **Type:** `Any` (R)
- **Description:** The buffer size for the electric energy source. `nil` if the entity doesn't have an electric energy source.  Write access is limited to the ElectricEnergyInterface type.

### `electric_drain`
- **Type:** `Any` (R)
- **Description:** The electric drain for the electric energy source. `nil` if the entity doesn't have an electric energy source.

### `electric_emissions_per_joule`
- **Type:** `Any` (R)
- **Description:** The table of emissions of this energy source in `pollution/Joule`, indexed by pollutant type. `nil` if the entity doesn't have an electric energy source. Multiplying values in the returned table by energy consumption in `Watt` gives `pollution/second`.

### `electric_network_id`
- **Type:** `Any` (R)
- **Description:** Returns the id of the electric network that this entity is connected to, if any.

### `electric_network_statistics`
- **Type:** `Any` (R)
- **Description:** The electric network statistics for this electric pole.
- **Restriction:** Can only be used if this is: **ElectricPole**

### `enable_logistics_while_moving`
- **Type:** `Any` (R)
- **Description:** Whether equipment grid logistics are enabled while this vehicle is moving.
- **Restriction:** Can only be used if this is: **Vehicle**

### `energy`
- **Type:** `Any` (R)
- **Description:** Energy stored in the entity's energy buffer (energy stored in electrical devices etc.). Always 0 for entities that don't have the concept of energy stored inside.

### `energy_generated_last_tick`
- **Type:** `Any` (R)
- **Description:** How much energy this generator generated in the last tick.
- **Restriction:** Can only be used if this is: **Generator**

### `entity_label`
- **Type:** `Any` (R)
- **Description:** The label on this spider-vehicle entity, if any. `nil` if this is not a spider-vehicle.

### `filter_slot_count`
- **Type:** `Any` (R)
- **Description:** The number of filter slots this inserter, loader, mining drill, asteroid collector or logistic storage container has. 0 if not one of those entities.

### `fluidbox`
- **Type:** `Any` (R)
- **Description:** Fluidboxes of this entity.

### `fluids_count`
- **Type:** `Any` (R)
- **Description:** Returns count of fluid storages. This includes fluid storages provided by fluidboxes but also covers other fluid storages like fluid turret's internal buffer and fluid wagon's fluid since they are not fluidbox and cannot be exposed through [LuaFluidBox](runtime:LuaFluidBox).

### `follow_offset`
- **Type:** `Any` (R)
- **Description:** The follow offset of this spidertron, if any entity is being followed. This is randomized each time the follow entity is set.
- **Restriction:** Can only be used if this is: **SpiderVehicle**

### `follow_target`
- **Type:** `Any` (R)
- **Description:** The follow target of this spidertron, if any.
- **Restriction:** Can only be used if this is: **SpiderVehicle**

### `friction_modifier`
- **Type:** `Any` (R)
- **Description:** Multiplies the car friction rate.
- **Restriction:** Can only be used if this is: **Car**

### `frozen`
- **Type:** `Any` (R)
- **Description:** Whether the freezable entity is currently frozen.  Always returns `false` if this entity is not considered [freezable](runtime:LuaEntity::is_freezable).
- **Restriction:** Can only be used if this is: **FreezableEntity**

### `ghost_localised_description`
- **Type:** `Any` (R)
- **Description:** 
- **Restriction:** Can only be used if this is: **Ghost**

### `ghost_localised_name`
- **Type:** `Any` (R)
- **Description:** Localised name of the entity or tile contained in this ghost.
- **Restriction:** Can only be used if this is: **Ghost**

### `ghost_name`
- **Type:** `Any` (R)
- **Description:** Name of the entity or tile contained in this ghost.
- **Restriction:** Can only be used if this is: **Ghost**

### `ghost_prototype`
- **Type:** `Any` (R)
- **Description:** The prototype of the entity or tile contained in this ghost.
- **Restriction:** Can only be used if this is: **Ghost**

### `ghost_type`
- **Type:** `Any` (R)
- **Description:** The prototype type of the entity or tile contained in this ghost.
- **Restriction:** Can only be used if this is: **Ghost**

### `ghost_unit_number`
- **Type:** `Any` (R)
- **Description:** The [unit_number](runtime:LuaEntity::unit_number) of the entity contained in this ghost. It is the same as the unit number of the [EntityWithOwnerPrototype](prototype:EntityWithOwnerPrototype) that was destroyed to create this ghost. If it was created by other means, or if the inner entity does not support unit numbers, this property is `nil`.
- **Restriction:** Can only be used if this is: **EntityGhost**

### `gps_tag`
- **Type:** `Any` (R)
- **Description:** Returns a [rich text](https://wiki.factorio.com/Rich_text) string containing this entity's position and surface name as a gps tag. [Printing](runtime:LuaGameScript::print) it will ping the location of the entity.

### `graphics_variation`
- **Type:** `Any` (R)
- **Description:** The graphics variation for this entity. `nil` if this entity doesn't use graphics variations.

### `grid`
- **Type:** `Any` (R)
- **Description:** This entity's equipment grid, if any.

### `health`
- **Type:** `Any` (R)
- **Description:** The current health of the entity, if any. Health is automatically clamped to be between `0` and max health (inclusive). Entities with a health of `0` can not be attacked.  To get the maximum possible health of this entity, see [LuaEntity::max_health](runtime:LuaEntity::max_health).

### `heat_neighbours`
- **Type:** `Any` (R)
- **Description:** The entities connected to this entities heat buffer.

### `held_stack`
- **Type:** `Any` (R)
- **Description:** The item stack currently held in an inserter's hand.
- **Restriction:** Can only be used if this is: **Inserter**

### `held_stack_position`
- **Type:** `Any` (R)
- **Description:** Current position of the inserter's "hand".
- **Restriction:** Can only be used if this is: **Inserter**

### `highlight_box_blink_interval`
- **Type:** `Any` (R)
- **Description:** The blink interval of this highlight box entity. `0` indicates no blink.
- **Restriction:** Can only be used if this is: **HighlightBox**

### `highlight_box_type`
- **Type:** `Any` (R)
- **Description:** The highlight box type of this highlight box entity.
- **Restriction:** Can only be used if this is: **HighlightBox**

### `ignore_unprioritised_targets`
- **Type:** `Any` (R)
- **Description:** Whether this turret shoots at targets that are not on its priority list.
- **Restriction:** Can only be used if this is: **Turret**

### `infinity_container_filters`
- **Type:** `Any` (R)
- **Description:** The filters for this infinity container.
- **Restriction:** Can only be used if this is: **InfinityContainer, InfinityCargoWagon**

### `initial_amount`
- **Type:** `Any` (R)
- **Description:** Count of initial resource units contained. `nil` if this is not an infinite resource.  If this is not an infinite resource, writing will produce an error.
- **Restriction:** Can only be used if this is: **ResourceEntity**

### `insert_plan`
- **Type:** `Any` (R)
- **Description:** The insert plan for this ghost or item request proxy.
- **Restriction:** Can only be used if this is: **EntityGhost, ItemRequestProxy**

### `inserter_filter_mode`
- **Type:** `Any` (R)
- **Description:** The filter mode for this filter inserter. `nil` if this inserter doesn't use filters.
- **Restriction:** Can only be used if this is: **Inserter**

### `inserter_spoil_priority`
- **Type:** `Any` (R)
- **Description:** The spoil priority for this inserter.
- **Restriction:** Can only be used if this is: **Inserter**

### `inserter_stack_size_override`
- **Type:** `Any` (R)
- **Description:** Sets the stack size limit on this inserter.  Set to `0` to reset.
- **Restriction:** Can only be used if this is: **Inserter**

### `inserter_target_pickup_count`
- **Type:** `Any` (R)
- **Description:** Returns the current target pickup count of the inserter.  This considers the circuit network, manual override and the inserter stack size limit based on technology.
- **Restriction:** Can only be used if this is: **Inserter**

### `is_entity_with_health`
- **Type:** `Any` (R)
- **Description:** If this entity is EntityWithHealth

### `is_entity_with_owner`
- **Type:** `Any` (R)
- **Description:** If this entity is EntityWithOwner

### `is_freezable`
- **Type:** `Any` (R)
- **Description:** Whether the entity is freezable and considered a FreezableEntity.

### `is_headed_to_trains_front`
- **Type:** `Any` (R)
- **Description:** If the rolling stock is facing train's front.
- **Restriction:** Can only be used if this is: **RollingStock**

### `is_military_target`
- **Type:** `Any` (R)
- **Description:** Whether this entity is a MilitaryTarget. Can be written to if [LuaEntityPrototype::allow_run_time_change_of_is_military_target](runtime:LuaEntityPrototype::allow_run_time_change_of_is_military_target) returns `true`.

### `is_updatable`
- **Type:** `Any` (R)
- **Description:** Whether the entity is updatable and considered an UpdatableEntity.

### `item_request_proxy`
- **Type:** `Any` (R)
- **Description:** The first found item request proxy targeting this entity.

### `item_requests`
- **Type:** `Any` (R)
- **Description:** Items this ghost will request when revived or items this item request proxy is requesting.

### `kills`
- **Type:** `Any` (R)
- **Description:** The number of units killed by this turret, artillery turret, or artillery wagon.
- **Restriction:** Can only be used if this is: **Turret**

### `last_user`
- **Type:** `Any` (R)
- **Description:** The last player that changed any setting on this entity. This includes building the entity, changing its color, or configuring its circuit network. `nil` if the last user is not part of the save anymore.
- **Restriction:** Can only be used if this is: **EntityWithOwner, DeconstructibleTileProxy, TileGhost**

### `link_id`
- **Type:** `Any` (R)
- **Description:** The link ID this linked container is using.
- **Restriction:** Can only be used if this is: **LinkedContainer**

### `linked_belt_neighbour`
- **Type:** `Any` (R)
- **Description:** Neighbour to which this linked belt is connected to, if any.  May return entity ghost which contains linked belt to which connection is made.
- **Restriction:** Can only be used if this is: **LinkedBelt**

### `linked_belt_type`
- **Type:** `Any` (R)
- **Description:** Type of linked belt. Changing type will also flip direction so the belt is out of the same side.  Can only be changed when linked belt is disconnected (has no neighbour set).
- **Restriction:** Can only be used if this is: **LinkedBelt**

### `loader_belt_stack_size_override`
- **Type:** `Any` (R)
- **Description:** The belt stack size override for this loader. Set to `0` to disable. Writing this value requires [LoaderPrototype::adjustable_belt_stack_size](prototype:LoaderPrototype::adjustable_belt_stack_size) to be `true`.
- **Restriction:** Can only be used if this is: **Loader**

### `loader_container`
- **Type:** `Any` (R)
- **Description:** The container entity this loader is pointing at/pulling from depending on the [LuaEntity::loader_type](runtime:LuaEntity::loader_type), if any.
- **Restriction:** Can only be used if this is: **Loader**

### `loader_filter_mode`
- **Type:** `Any` (R)
- **Description:** The filter mode for this loader. `nil` if this loader does not support filters.
- **Restriction:** Can only be used if this is: **Loader**

### `loader_type`
- **Type:** `Any` (R)
- **Description:** Whether this loader gets items from or puts item into a container.
- **Restriction:** Can only be used if this is: **Loader**

### `localised_description`
- **Type:** `Any` (R)
- **Description:** 

### `localised_name`
- **Type:** `Any` (R)
- **Description:** Localised name of the entity.

### `logistic_cell`
- **Type:** `Any` (R)
- **Description:** The logistic cell this entity is a part of. Will be `nil` if this entity is not a part of any logistic cell.

### `logistic_network`
- **Type:** `Any` (R)
- **Description:** The logistic network this entity is a part of, or `nil` if this entity is not a part of any logistic network.

### `max_health`
- **Type:** `Any` (R)
- **Description:** Max health of this entity.

### `minable`
- **Type:** `Any` (R)
- **Description:** Not minable entities can still be destroyed.  Tells if entity reports as being minable right now. This takes into account `minable_flag` and entity specific conditions (for example rail under rolling stocks is not minable, vehicle with passenger is not minable).  Write to this field since 2.0.26 is deprecated and it will result in write to `minable_flag` instead.

### `minable_flag`
- **Type:** `Any` (R)
- **Description:** Script controlled flag that allows entity to be mined.

### `mining_area`
- **Type:** `Any` (R)
- **Description:** Area in which this mining drill looks for resources to mine.
- **Restriction:** Can only be used if this is: **MiningDrill**

### `mining_drill_filter_mode`
- **Type:** `Any` (R)
- **Description:** The filter mode for this mining drill. `nil` if this mining drill doesn't have filters.
- **Restriction:** Can only be used if this is: **MiningDrill**

### `mining_progress`
- **Type:** `Any` (R)
- **Description:** The mining progress for this mining drill. Is a number in range [0, mining_target.prototype.mineable_properties.mining_time]. `nil` if this isn't a mining drill.

### `mining_target`
- **Type:** `Any` (R)
- **Description:** The mining target, if any.
- **Restriction:** Can only be used if this is: **MiningDrill**

### `mirroring`
- **Type:** `Any` (R)
- **Description:** Whether the entity is currently mirrored. This state is referred to as `flipped` elsewhere, such as on the [on_player_flipped_entity](runtime:on_player_flipped_entity) event.  If an entity is mirrored, it is flipped over the axis that is pointing in the entity's direction. For example if a mirrored entity is facing north, everything that was defined to be facing east in the prototype now faces west.

### `name`
- **Type:** `Any` (R)
- **Description:** Name of the entity prototype. E.g. "inserter" or "fast-inserter".

### `name_tag`
- **Type:** `Any` (R)
- **Description:** Name tag of this entity. Returns `nil` if entity has no name tag. When name tag is already used by other entity, the name will be removed from the other entity. Entity name tags can also be set in the entity "extra settings" GUI in the map editor.

### `neighbour_bonus`
- **Type:** `Any` (R)
- **Description:** The current total neighbour bonus of this reactor.
- **Restriction:** Can only be used if this is: **Reactor**

### `neighbours`
- **Type:** `Any` (R)
- **Description:** A list of neighbours for certain types of entities. Applies to underground belts, walls, gates, reactors, heat pipes, cliffs, and pipe-connectable entities.

### `object_name`
- **Type:** `Any` (R)
- **Description:** The class name of this object. Available even when `valid` is false. For LuaStruct objects it may also be suffixed with a dotted path to a member of the struct.

### `operable`
- **Type:** `Any` (R)
- **Description:** Player can't open gui of this entity and he can't quick insert/input stuff in to the entity when it is not operable.

### `orientation`
- **Type:** `Any` (R)
- **Description:** The smooth orientation of this entity. For turrets this is the orientation of the weapon.

### `owned_plants`
- **Type:** `Any` (R)
- **Description:** Plants registered by this agricultural tower. One plant can be registered in multiple agricultural towers.
- **Restriction:** Can only be used if this is: **AgriculturalTower**

### `parameters`
- **Type:** `Any` (R)
- **Description:** 
- **Restriction:** Can only be used if this is: **ProgrammableSpeaker**

### `pickup_from_left_lane`
- **Type:** `Any` (R)
- **Description:** For inserters taking items from transport belt connectables, this determines whether the inserter is allowed to take items from the left lane.
- **Restriction:** Can only be used if this is: **Inserter**

### `pickup_from_right_lane`
- **Type:** `Any` (R)
- **Description:** For inserters taking items from transport belt connectables, this determines whether the inserter is allowed to take items from the right lane.
- **Restriction:** Can only be used if this is: **Inserter**

### `pickup_position`
- **Type:** `Any` (R)
- **Description:** Where the inserter will pick up items from.  Inserters must have `allow_custom_vectors` set to true on their prototype to allow changing the pickup position.
- **Restriction:** Can only be used if this is: **Inserter**

### `pickup_target`
- **Type:** `Any` (R)
- **Description:** The entity this inserter will attempt to pick up items from. If there are multiple possible entities at the pick-up point, writing to this attribute allows a mod to choose which one to pick up items from. The entity needs to collide with the tile box under the pick-up position. `nil` if there is no entity to pull items from.
- **Restriction:** Can only be used if this is: **Inserter**

### `player`
- **Type:** `Any` (R)
- **Description:** The player connected to this character, if any.
- **Restriction:** Can only be used if this is: **Character**

### `pollution_bonus`
- **Type:** `Any` (R)
- **Description:** The pollution bonus of this entity.

### `power_production`
- **Type:** `Any` (R)
- **Description:** The power production specific to the ElectricEnergyInterface entity type.
- **Restriction:** Can only be used if this is: **ElectricEnergyInterface**

### `power_switch_state`
- **Type:** `Any` (R)
- **Description:** The state of this power switch.
- **Restriction:** Can only be used if this is: **PowerSwitch**

### `power_usage`
- **Type:** `Any` (R)
- **Description:** The power usage specific to the ElectricEnergyInterface entity type.
- **Restriction:** Can only be used if this is: **ElectricEnergyInterface**

### `previous_recipe`
- **Type:** `Any` (R)
- **Description:** The previous recipe this furnace was using, if any.
- **Restriction:** Can only be used if this is: **Furnace**

### `priority_targets`
- **Type:** `Any` (R)
- **Description:** The priority targets for this turret (if any).
- **Restriction:** Can only be used if this is: **Turret**

### `procession_tick`
- **Type:** `Any` (R)
- **Description:** how far into the current procession the cargo pod is.
- **Restriction:** Can only be used if this is: **CargoPod**

### `productivity_bonus`
- **Type:** `Any` (R)
- **Description:** The productivity bonus of this entity.  This includes force based bonuses as well as beacon/module bonuses.

### `products_finished`
- **Type:** `Any` (R)
- **Description:** The number of products this machine finished crafting in its lifetime.
- **Restriction:** Can only be used if this is: **CraftingMachine**

### `prototype`
- **Type:** `Any` (R)
- **Description:** The entity prototype of this entity.

### `proxy_target`
- **Type:** `Any` (R)
- **Description:** The target entity for this item-request-proxy, if any.
- **Restriction:** Can only be used if this is: **ItemRequestProxy**

### `proxy_target_entity`
- **Type:** `Any` (R)
- **Description:** Entity of which inventory is exposed by this ProxyContainer
- **Restriction:** Can only be used if this is: **ProxyContainer**

### `proxy_target_inventory`
- **Type:** `Any` (R)
- **Description:** Inventory index of the inventory that is exposed by this ProxyContainer
- **Restriction:** Can only be used if this is: **ProxyContainer**

### `pump_rail_target`
- **Type:** `Any` (R)
- **Description:** The rail target of this pump, if any.
- **Restriction:** Can only be used if this is: **Pump**

### `pumped_last_tick`
- **Type:** `Any` (R)
- **Description:** The amount of fluid moved by this offshore pump or normal pump in the last tick.
- **Restriction:** Can only be used if this is: **OffshorePump, Pump**

### `quality`
- **Type:** `Any` (R)
- **Description:** The quality of this entity.  Not all entities support quality and will give the "normal" quality back if they don't.

### `radar_scan_progress`
- **Type:** `Any` (R)
- **Description:** The current radar scan progress, as a number in range `[0, 1]`.
- **Restriction:** Can only be used if this is: **Radar**

### `rail_layer`
- **Type:** `Any` (R)
- **Description:** Gets rail layer of a given signal
- **Restriction:** Can only be used if this is: **RailSignal, RailChainSignal**

### `rail_length`
- **Type:** `Any` (R)
- **Description:** Length of this rail piece.
- **Restriction:** Can only be used if this is: **Rail**

### `recipe_locked`
- **Type:** `Any` (R)
- **Description:** When locked; the recipe in this assembling machine can't be changed by the player.
- **Restriction:** Can only be used if this is: **AssemblingMachine**

### `relative_turret_orientation`
- **Type:** `Any` (R)
- **Description:** The relative orientation of the vehicle turret, artillery turret, artillery wagon. `nil` if this entity isn't a vehicle with a vehicle turret or artillery turret/wagon.  Writing does nothing if the vehicle doesn't have a turret.  For the turret orientation of non-artillery turrets, use [LuaEntity::orientation](runtime:LuaEntity::orientation).

### `removal_plan`
- **Type:** `Any` (R)
- **Description:** The removal plan for this item request proxy.
- **Restriction:** Can only be used if this is: **ItemRequestProxy**

### `remove_unfiltered_items`
- **Type:** `Any` (R)
- **Description:** Whether items not included in this infinity container filters should be removed from the container.
- **Restriction:** Can only be used if this is: **InfinityContainer, InfinityCargoWagon**

### `render_player`
- **Type:** `Any` (R)
- **Description:** The player that this `simple-entity-with-owner`, `simple-entity-with-force`, or `highlight-box` is visible to. `nil` when this entity is rendered for all players.

### `render_to_forces`
- **Type:** `Any` (R)
- **Description:** The forces that this `simple-entity-with-owner` or `simple-entity-with-force` is visible to. `nil` or an empty array when this entity is rendered for all forces.  Reading will always give an array of [LuaForce](runtime:LuaForce)

### `request_from_buffers`
- **Type:** `Any` (R)
- **Description:** Whether this requester chest is set to also request from buffer chests.  Useable only on entities that have requester slots.

### `result_quality`
- **Type:** `Any` (R)
- **Description:** The quality produced when this crafting machine finishes crafting. `nil` when crafting is not in progress.  Note: Writing `nil` is not allowed.
- **Restriction:** Can only be used if this is: **CraftingMachine**

### `robot_order_queue`
- **Type:** `Any` (R)
- **Description:** Get the current queue of robot orders.
- **Restriction:** Can only be used if this is: **ConstructionRobot, LogisticRobot**

### `rocket`
- **Type:** `Any` (R)
- **Description:** The rocket silo rocket this cargo pod is attached to, or rocket silo rocket attached to this rocket silo - if any.

### `rocket_parts`
- **Type:** `Any` (R)
- **Description:** Number of rocket parts in the silo.
- **Restriction:** Can only be used if this is: **RocketSilo**

### `rocket_silo_status`
- **Type:** `Any` (R)
- **Description:** The status of this rocket silo entity.
- **Restriction:** Can only be used if this is: **RocketSilo**

### `rotatable`
- **Type:** `Any` (R)
- **Description:** When entity is not to be rotatable (inserter, transport belt etc), it can't be rotated by player using the R key.  Entities that are not rotatable naturally (like chest or furnace) can't be set to be rotatable.

### `secondary_bounding_box`
- **Type:** `Any` (R)
- **Description:** The secondary bounding box of this entity or `nil` if it doesn't have one. This only exists for curved rails, and is automatically determined by the game.

### `secondary_selection_box`
- **Type:** `Any` (R)
- **Description:** The secondary selection box of this entity or `nil` if it doesn't have one. This only exists for curved rails, and is automatically determined by the game.

### `segmented_unit`
- **Type:** `Any` (R)
- **Description:** The segmented unit object that the segment entity is a part of.
- **Restriction:** Can only be used if this is: **Segment**

### `selected_gun_index`
- **Type:** `Any` (R)
- **Description:** Index of the currently selected weapon slot of this character, car, or spidertron. `nil` if this entity doesn't have guns.
- **Restriction:** Can only be used if this is: **Character, Car, SpiderVehicle**

### `selection_box`
- **Type:** `Any` (R)
- **Description:** [LuaEntityPrototype::selection_box](runtime:LuaEntityPrototype::selection_box) around entity's given position and respecting the current entity orientation.

### `shooting_target`
- **Type:** `Any` (R)
- **Description:** The shooting target for this turret, if any. Can't be set to `nil` via script.
- **Restriction:** Can only be used if this is: **Turret**

### `signal_state`
- **Type:** `Any` (R)
- **Description:** The state of this rail signal.
- **Restriction:** Can only be used if this is: **RailSignal, RailChainSignal**

### `spawn_shift`
- **Type:** `Any` (R)
- **Description:** 
- **Restriction:** Can only be used if this is: **Spawner**

### `spawning_cooldown`
- **Type:** `Any` (R)
- **Description:** 
- **Restriction:** Can only be used if this is: **Spawner**

### `speed`
- **Type:** `Any` (R)
- **Description:** The current speed if this is a car, rolling stock, projectile or spidertron, or the maximum speed if this is a unit. The speed is in tiles per tick. `nil` if this is not a car, rolling stock, unit, projectile or spidertron.  Only the speed of units, cars, and projectiles are writable.

### `speed_bonus`
- **Type:** `Any` (R)
- **Description:** The speed bonus of this entity.  This includes force based bonuses as well as beacon/module bonuses.

### `splitter_filter`
- **Type:** `Any` (R)
- **Description:** The filter for this splitter, if any is set.
- **Restriction:** Can only be used if this is: **Splitter, LaneSplitter**

### `splitter_input_priority`
- **Type:** `Any` (R)
- **Description:** The input priority for this splitter.
- **Restriction:** Can only be used if this is: **Splitter, LaneSplitter**

### `splitter_output_priority`
- **Type:** `Any` (R)
- **Description:** The output priority for this splitter.
- **Restriction:** Can only be used if this is: **Splitter, LaneSplitter**

### `stack`
- **Type:** `Any` (R)
- **Description:** 
- **Restriction:** Can only be used if this is: **ItemEntity**

### `status`
- **Type:** `Any` (R)
- **Description:** The status of this entity, if any.  This is always the actual status of the entity, even if [LuaEntity::custom_status](runtime:LuaEntity::custom_status) is set.

### `sticked_to`
- **Type:** `Any` (R)
- **Description:** The entity this sticker is sticked to.
- **Restriction:** Can only be used if this is: **Sticker**

### `sticker_vehicle_modifiers`
- **Type:** `Any` (R)
- **Description:** The vehicle modifiers applied to this entity through the attached stickers.

### `stickers`
- **Type:** `Any` (R)
- **Description:** The sticker entities attached to this entity, if any.

### `storage_filter`
- **Type:** `Any` (R)
- **Description:** The storage filter for this logistic storage container.  Useable only on logistic containers with the `"storage"` [logistic_mode](runtime:LuaEntityPrototype::logistic_mode).

### `supports_direction`
- **Type:** `Any` (R)
- **Description:** Whether the entity has direction. When it is false for this entity, it will always return north direction when asked for.

### `tags`
- **Type:** `Any` (R)
- **Description:** The tags associated with this entity ghost. `nil` if this is not an entity ghost or when the ghost has no tags.

### `temperature`
- **Type:** `Any` (R)
- **Description:** The temperature of this entity's heat energy source. `nil` if this entity does not use a heat energy source.

### `tick_grown`
- **Type:** `Any` (R)
- **Description:** The tick when this plant is fully grown.
- **Restriction:** Can only be used if this is: **Plant**

### `tick_of_last_attack`
- **Type:** `Any` (R)
- **Description:** The last tick this character entity was attacked.
- **Restriction:** Can only be used if this is: **Character**

### `tick_of_last_damage`
- **Type:** `Any` (R)
- **Description:** The last tick this character entity was damaged.
- **Restriction:** Can only be used if this is: **Character**

### `tile_height`
- **Type:** `Any` (R)
- **Description:** Specifies the tiling size of the entity, is used to decide, if the center should be in the center of the tile (odd tile size dimension) or on the tile border (even tile size dimension). Uses the current direction of the entity.

### `tile_width`
- **Type:** `Any` (R)
- **Description:** Specifies the tiling size of the entity, is used to decide, if the center should be in the center of the tile (odd tile size dimension) or on the tile border (even tile size dimension). Uses the current direction of the entity.

### `time_to_live`
- **Type:** `Any` (R)
- **Description:** The ticks left before a combat robot, highlight box, smoke, or sticker entity is destroyed.
- **Restriction:** Can only be used if this is: **CombatRobot, HighlightBox, Smoke, Sticker**

### `time_to_next_effect`
- **Type:** `Any` (R)
- **Description:** The ticks until the next trigger effect of this smoke-with-trigger.
- **Restriction:** Can only be used if this is: **SmokeWithTrigger**

### `timeout`
- **Type:** `Any` (R)
- **Description:** The timeout that's left on this landmine in ticks. It describes the time between the landmine being placed and it being armed.
- **Restriction:** Can only be used if this is: **LandMine**

### `to_be_looted`
- **Type:** `Any` (R)
- **Description:** Will this item entity be picked up automatically when the player walks over it?
- **Restriction:** Can only be used if this is: **ItemEntity**

### `torso_orientation`
- **Type:** `Any` (R)
- **Description:** The torso orientation of this spider vehicle.
- **Restriction:** Can only be used if this is: **SpiderVehicle**

### `train`
- **Type:** `Any` (R)
- **Description:** The train this rolling stock belongs to, if any. `nil` if this is not a rolling stock.

### `train_stop_priority`
- **Type:** `Any` (R)
- **Description:** Priority of this train stop.
- **Restriction:** Can only be used if this is: **TrainStop**

### `trains_count`
- **Type:** `Any` (R)
- **Description:** Amount of trains related to this particular train stop. Includes train stopped at this train stop (until it finds a path to next target) and trains having this train stop as goal or waypoint.  Train may be included multiple times when braking distance covers this train stop multiple times.  Value may be read even when train stop has no control behavior.
- **Restriction:** Can only be used if this is: **TrainStop**

### `trains_in_block`
- **Type:** `Any` (R)
- **Description:** The number of trains in this rail block for this rail entity.
- **Restriction:** Can only be used if this is: **Rail**

### `trains_limit`
- **Type:** `Any` (R)
- **Description:** Amount of trains above which no new trains will be sent to this train stop. Writing nil will disable the limit (will set a maximum possible value).  When a train stop has a control behavior with wire connected and set_trains_limit enabled, this value will be overwritten by it.
- **Restriction:** Can only be used if this is: **TrainStop**

### `transitional_request_target`
- **Type:** `Any` (R)
- **Description:** The space platform in orbit this rocket silo is automatically requesting items for.
- **Restriction:** Can only be used if this is: **RocketSilo**

### `tree_color_index`
- **Type:** `Any` (R)
- **Description:** Index of the tree color.
- **Restriction:** Can only be used if this is: **Tree**

### `tree_color_index_max`
- **Type:** `Any` (R)
- **Description:** Maximum index of the tree colors.
- **Restriction:** Can only be used if this is: **Tree**

### `tree_gray_stage_index`
- **Type:** `Any` (R)
- **Description:** Index of the tree gray stage
- **Restriction:** Can only be used if this is: **Tree**

### `tree_gray_stage_index_max`
- **Type:** `Any` (R)
- **Description:** Maximum index of the tree gray stages.
- **Restriction:** Can only be used if this is: **Tree**

### `tree_stage_index`
- **Type:** `Any` (R)
- **Description:** Index of the tree stage.
- **Restriction:** Can only be used if this is: **Tree**

### `tree_stage_index_max`
- **Type:** `Any` (R)
- **Description:** Maximum index of the tree stages.
- **Restriction:** Can only be used if this is: **Tree**

### `type`
- **Type:** `Any` (R)
- **Description:** The entity prototype type of this entity.

### `unit_number`
- **Type:** `Any` (R)
- **Description:** A unique number identifying this entity for the lifetime of the save. These are allocated sequentially, and not re-used (until overflow).  Only entities inheriting from [EntityWithOwnerPrototype](prototype:EntityWithOwnerPrototype), as well as [ItemRequestProxyPrototype](prototype:ItemRequestProxyPrototype) and [EntityGhostPrototype](prototype:EntityGhostPrototype) are assigned a unit number. Returns `nil` otherwise.

### `units`
- **Type:** `Any` (R)
- **Description:** The units associated with this spawner entity.
- **Restriction:** Can only be used if this is: **Spawner**

### `use_filters`
- **Type:** `Any` (R)
- **Description:** If set to 'true', this inserter will use filtering logic.  This has no effect if the prototype does not support filters.
- **Restriction:** Can only be used if this is: **Inserter**

### `use_transitional_requests`
- **Type:** `Any` (R)
- **Description:** When true, the rocket silo will automatically request items for space platforms in orbit.  Setting the value will have no effect when the silo doesn't support logistics.
- **Restriction:** Can only be used if this is: **RocketSilo**

### `valid`
- **Type:** `Any` (R)
- **Description:** Is this object valid? This Lua object holds a reference to an object within the game engine. It is possible that the game-engine object is removed whilst a mod still holds the corresponding Lua object. If that happens, the object becomes invalid, i.e. this attribute will be `false`. Mods are advised to check for object validity if any change to the game state might have occurred between the creation of the Lua object and its access.

### `valve_threshold_override`
- **Type:** `Any` (R)
- **Description:** The threshold override of this valve, or `nil` if an override is not defined.  If no override is defined, the threshold is taken from [LuaEntityPrototype::valve_threshold](runtime:LuaEntityPrototype::valve_threshold).
- **Restriction:** Can only be used if this is: **Valve**

### `vehicle_automatic_targeting_parameters`
- **Type:** `Any` (R)
- **Description:** Read when this spidertron auto-targets enemies
- **Restriction:** Can only be used if this is: **SpiderVehicle**

## Methods
### `add_autopilot_destination(position: MapPosition)`
- Adds the given position to this spidertron's autopilot's queue of destinations.
- **Restriction:** Can only be used if this is: **SpiderVehicle**

### `add_market_item(offer: Offer)`
- Offer a thing on the market.
- **Restriction:** Can only be used if this is: **Market**

### `apply_upgrade() -> LuaEntity?, LuaEntity?`
- Upgrades this entity in place if it's marked to be upgraded.

### `can_be_destroyed() -> boolean`
- Whether the entity can be destroyed

### `can_set_inventory_filter(filter: ItemFilter, index: uint32, inventory_index: defines.inventory) -> boolean`
- The same as [LuaInventory::can_set_filter](runtime:LuaInventory::can_set_filter) but also works for ghosts where the inventory is not available through [LuaControl::get_inventory](runtime:LuaControl::get_inventory).

### `can_shoot(position: MapPosition, target: LuaEntity) -> boolean`
- Whether this character can shoot the given entity or position.
- **Restriction:** Can only be used if this is: **Character**

### `can_wires_reach(entity: LuaEntity) -> boolean`
- Can wires reach between these entities.

### `cancel_deconstruction(force: ForceID, player?: PlayerIdentification)`
- Cancels deconstruction if it is scheduled, does nothing otherwise.

### `cancel_upgrade(force: ForceID, player?: PlayerIdentification) -> boolean`
- Cancels upgrade if it is scheduled, does nothing otherwise.

### `clear_fluid_inside()`
- Remove all fluids from this entity.

### `clear_market_items()`
- Removes all offers from a market.
- **Restriction:** Can only be used if this is: **Market**

### `clone(create_build_effect_smoke?: boolean, force?: ForceID, position: MapPosition, surface?: LuaSurface) -> LuaEntity?`
- Clones this entity.

### `connect_linked_belts(neighbour?: LuaEntity)`
- Connects current linked belt with another one.  Neighbours have to be of different type. If given linked belt is connected to something else it will be disconnected first. If provided neighbour is connected to something else it will also be disconnected first. Automatically updates neighbour to be connected back to this one.
- **Restriction:** Can only be used if this is: **LinkedBelt**

### `connect_rolling_stock(direction: defines.rail_direction) -> boolean`
- Connects the rolling stock in the given direction.
- **Restriction:** Can only be used if this is: **RollingStock**

### `copy_settings(by_player?: PlayerIdentification, entity: LuaEntity) -> ItemWithQualityCounts`
- Copies settings from the given entity onto this entity.

### `create_build_effect_smoke()`
- Creates the same smoke that is created when you place a building by hand.  You can play the building sound to go with it by using [LuaSurface::play_sound](runtime:LuaSurface::play_sound), eg: `entity.surface.play_sound{path="entity-build/"..entity.prototype.name, position=entity.position}`

### `create_cargo_pod(cargo_hatch?: LuaCargoHatch) -> LuaEntity?`
- Creates a cargo pod if possible.  Cargo pod will be created with [invalid](runtime:defines.cargo_destination.invalid) destination type. Setting [cargo_pod_destination](runtime:LuaEntity::cargo_pod_destination) will cause it to launch.
- **Restriction:** Can only be used if this is: **RocketSilo, CargoLandingPad, SpacePlatformHub**

### `damage(cause?: LuaEntity, damage: float, force: ForceID, source?: LuaEntity, type?: DamageTypeID) -> float`
- Damages the entity.
- **Restriction:** Can only be used if this is: **EntityWithHealth**

### `deplete()`
- Depletes and destroys this resource entity.
- **Restriction:** Can only be used if this is: **ResourceEntity**

### `destroy(do_cliff_correction?: boolean, player?: PlayerIdentification, raise_destroy?: boolean, undo_index?: uint32) -> boolean`
- Destroys the entity.  Not all entities can be destroyed - things such as rails under trains cannot be destroyed until the train is moved or destroyed.

### `die(cause?: LuaEntity, force?: ForceID) -> boolean`
- Immediately kills the entity. Does nothing if the entity doesn't have health.  Unlike [LuaEntity::destroy](runtime:LuaEntity::destroy), `die` will trigger the [on_entity_died](runtime:on_entity_died) event and the entity will produce a corpse and drop loot if it has any.

### `disconnect_linked_belts()`
- Disconnects linked belt from its neighbour.
- **Restriction:** Can only be used if this is: **LinkedBelt**

### `disconnect_rolling_stock(direction: defines.rail_direction) -> boolean`
- Tries to disconnect this rolling stock in the given direction.
- **Restriction:** Can only be used if this is: **RollingStock**

### `force_finish_ascending()`
- Take an ascending cargo pod and safely make it skip all animation and immediately switch surface.
- **Restriction:** Can only be used if this is: **CargoPod**

### `force_finish_descending()`
- Take a descending cargo pod and safely make it arrive and deposit cargo.
- **Restriction:** Can only be used if this is: **CargoPod**

### `get_beacon_effect_receivers() -> Array<LuaEntity>`
- Returns a table with all entities affected by this beacon
- **Restriction:** Can only be used if this is: **Beacon**

### `get_beacons() -> Array<LuaEntity>?`
- Returns a table with all beacons affecting this effect receiver. Can only be used when the entity has an effect receiver (AssemblingMachine, Furnace, Lab, MiningDrills)

### `get_beam_source() -> BeamTarget?`
- Get the source of this beam.
- **Restriction:** Can only be used if this is: **Beam**

### `get_beam_target() -> BeamTarget?`
- Get the target of this beam.
- **Restriction:** Can only be used if this is: **Beam**

### `get_burnt_result_inventory() -> LuaInventory?`
- The burnt result inventory for this entity or `nil` if this entity doesn't have a burnt result inventory.

### `get_cargo_bays() -> Array<LuaEntity>`
- Gets the cargo bays connected to this cargo landing pad or space platform hub.
- **Restriction:** Can only be used if this is: **CargoLandingPad, SpacePlatformHub**

### `get_child_signals() -> Array<LuaEntity>`
- Returns all child signals. Child signals can be either RailSignal or RailChainSignal. Child signals are signals which are checked by this signal to determine a chain state.
- **Restriction:** Can only be used if this is: **RailChainSignal**

### `get_circuit_network(wire_connector_id: defines.wire_connector_id) -> LuaCircuitNetwork?`
- 

### `get_connected_rail(rail_connection_direction: defines.rail_connection_direction, rail_direction: defines.rail_direction) -> LuaEntity?, defines.rail_direction?, defines.rail_connection_direction?`
- 
- **Restriction:** Can only be used if this is: **Rail**

### `get_connected_rails() -> Array<LuaEntity>`
- Get the rails that this signal is connected to.
- **Restriction:** Can only be used if this is: **RailSignal, RailChainSignal**

### `get_connected_rolling_stock(direction: defines.rail_direction) -> LuaEntity?, defines.rail_direction?`
- Gets rolling stock connected to the given end of this stock.
- **Restriction:** Can only be used if this is: **RollingStock**

### `get_control_behavior() -> LuaControlBehavior?`
- Gets the control behavior of the entity (if any).

### `get_damage_to_be_taken() -> float?`
- Returns the amount of damage to be taken by this entity.

### `get_driver() -> LuaEntity | LuaPlayer?`
- Gets the driver of this vehicle if any.
- **Restriction:** Can only be used if this is: **Vehicle**

### `get_electric_input_flow_limit(quality?: QualityID) -> double?`
- The input flow limit for the electric energy source. `nil` if the entity doesn't have an electric energy source.

### `get_electric_output_flow_limit(quality?: QualityID) -> double?`
- The output flow limit for the electric energy source. `nil` if the entity doesn't have an electric energy source.

### `get_filter(slot_index: uint32) -> ItemFilter | EntityID | AsteroidChunkID?`
- Get the filter for a slot in an inserter, loader, mining drill, asteroid collector, or logistic storage container. The entity must allow filters.

### `get_fluid(index: uint32) -> Fluid?`
- Gets fluid of the index-th fluid storage. This includes fluidbox and non-fluidbox fluid storages like fluid wagon contents. Refer to [LuaEntity::fluids_count](runtime:LuaEntity::fluids_count) for more information on available storages.

### `get_fluid_contents() -> Dict<string, FluidAmount>`
- Get amounts of all fluids in this entity.  If information about fluid temperatures is required, [LuaEntity::get_fluid](runtime:LuaEntity::get_fluid) or [LuaEntity::fluidbox](runtime:LuaEntity::fluidbox) should be used instead.

### `get_fluid_count(fluid?: string) -> double`
- Get the amount of all or some fluid in this entity.  If information about fluid temperatures is required, [LuaEntity::fluidbox](runtime:LuaEntity::fluidbox) should be used instead.

### `get_fluid_source_fluid() -> string?`
- Checks what is expected fluid to be produced from the offshore pump's source tile. It accounts for visible tile, hidden tile and double hidden tile. It ignores currently set fluid box filter.
- **Restriction:** Can only be used if this is: **OffshorePump**

### `get_fluid_source_tile() -> TilePosition`
- Gives TilePosition of a tile which this offshore pump uses to check what fluid should be produced.
- **Restriction:** Can only be used if this is: **OffshorePump**

### `get_fuel_inventory() -> LuaInventory?`
- The fuel inventory for this entity or `nil` if this entity doesn't have a fuel inventory.

### `get_health_ratio() -> float?`
- The health ratio of this entity between 1 and 0 (for full health and no health respectively).

### `get_heat_setting() -> HeatSetting`
- Gets the heat setting for this heat interface.
- **Restriction:** Can only be used if this is: **HeatInterface**

### `get_inbound_signals() -> Array<LuaEntity>`
- Returns all signals guarding entrance to a rail block this rail belongs to.
- **Restriction:** Can only be used if this is: **Rail**

### `get_infinity_container_filter(index: uint32) -> InfinityInventoryFilter?`
- Gets the filter for this infinity container at the given index, or `nil` if the filter index doesn't exist or is empty.
- **Restriction:** Can only be used if this is: **InfinityContainer, InfinityCargoWagon**

### `get_infinity_pipe_filter() -> InfinityPipeFilter?`
- Gets the filter for this infinity pipe, or `nil` if the filter is empty.
- **Restriction:** Can only be used if this is: **InfinityPipe**

### `get_inventory_bar(inventory_index: defines.inventory) -> uint32`
- The same as [LuaInventory::get_bar](runtime:LuaInventory::get_bar) but also works for ghosts where the inventory is not available through [LuaControl::get_inventory](runtime:LuaControl::get_inventory).

### `get_inventory_filter(index: uint32, inventory_index: defines.inventory) -> ItemFilter?`
- The same as [LuaInventory::get_filter](runtime:LuaInventory::get_filter) but also works for ghosts where the inventory is not available through [LuaControl::get_inventory](runtime:LuaControl::get_inventory).

### `get_inventory_size_override(inventory_index: defines.inventory) -> uint16?`
- Gets the inventory size override of the selected inventory if size override was set using [set_inventory_size_override](runtime:LuaEntity::set_inventory_size_override).
- **Restriction:** Can only be used if this is: **ContainerEntity, CargoWagon**

### `get_item_insert_specification(position: MapPosition) -> uint32, float`
- Get an item insert specification onto a belt connectable: for a given map position provides into which line at what position item should be inserted to be closest to the provided position.
- **Restriction:** Can only be used if this is: **TransportBeltConnectable**

### `get_line_item_position(index: uint32, position: float) -> MapPosition`
- Get a map position related to a position on a transport line.
- **Restriction:** Can only be used if this is: **TransportBeltConnectable**

### `get_logistic_point(index?: defines.logistic_member_index) -> LuaLogisticPoint | Array<LuaLogisticPoint>?`
- Gets all the `LuaLogisticPoint`s that this entity owns. Optionally returns only the point specified by the index parameter.

### `get_logistic_sections() -> LuaLogisticSections?`
- Gives logistic sections of this entity if it uses logistic sections.

### `get_market_items() -> Array<Offer>`
- Get all offers in a market as an array.
- **Restriction:** Can only be used if this is: **Market**

### `get_max_transport_line_index() -> uint32`
- Get the maximum transport line index of a belt or belt connectable entity.
- **Restriction:** Can only be used if this is: **TransportBeltConnectable**

### `get_module_inventory() -> LuaInventory?`
- Inventory for storing modules of this entity; `nil` if this entity has no module inventory.

### `get_movement() -> Vector`
- Gets the combined movement vector (direction and speed) of this combat robot or asteroid. The entity moves by this vector each tick.  Note that for combat robots this does not include the constant drift in the direction they are facing.
- **Restriction:** Can only be used if this is: **CombatRobot, Asteroid**

### `get_or_create_control_behavior() -> LuaControlBehavior?`
- Gets (and or creates if needed) the control behavior of the entity.

### `get_outbound_signals() -> Array<LuaEntity>`
- Returns all signals guarding exit from a rail block this rail belongs to.
- **Restriction:** Can only be used if this is: **Rail**

### `get_output_inventory() -> LuaInventory?`
- Gets the entity's output inventory if it has one.

### `get_parent_signals() -> Array<LuaEntity>`
- Returns all parent signals. Parent signals are always RailChainSignal. Parent signals are those signals that are checking state of this signal to determine their own chain state.
- **Restriction:** Can only be used if this is: **RailSignal, RailChainSignal**

### `get_passenger() -> LuaEntity | LuaPlayer?`
- Gets the passenger of this car, spidertron, or cargo pod if any.  This differs over [LuaEntity::get_driver](runtime:LuaEntity::get_driver) in that for cars, the passenger can't drive the car.
- **Restriction:** Can only be used if this is: **Car, SpiderVehicle, CargoPod**

### `get_priority_target(index: uint32) -> LuaEntityPrototype?`
- Get the entity ID at the specified position in the turret's priority list.

### `get_radius() -> double`
- The radius of this entity. The radius is defined as half the distance between the top left corner and bottom right corner of the collision box.

### `get_rail_end(direction: defines.rail_direction) -> LuaRailEnd`
- Gets a LuaRailEnd object for specified end of this rail
- **Restriction:** Can only be used if this is: **Rail**

### `get_rail_segment_end(direction: defines.rail_direction) -> LuaEntity, defines.rail_direction`
- Get the rail at the end of the rail segment this rail is in.  A rail segment is a continuous section of rail with no branches, signals, nor train stops.
- **Restriction:** Can only be used if this is: **Rail**

### `get_rail_segment_length() -> double`
- Get the length of the rail segment this rail is in.  A rail segment is a continuous section of rail with no branches, signals, nor train stops.
- **Restriction:** Can only be used if this is: **Rail**

### `get_rail_segment_overlaps() -> Array<LuaEntity>`
- Get a rail from each rail segment that overlaps with this rail's rail segment.  A rail segment is a continuous section of rail with no branches, signals, nor train stops.
- **Restriction:** Can only be used if this is: **Rail**

### `get_rail_segment_rails(direction: defines.rail_direction) -> Array<LuaEntity>`
- Get all rails of a rail segment this rail is in  A rail segment is a continuous section of rail with no branches, signals, nor train stops.
- **Restriction:** Can only be used if this is: **Rail**

### `get_rail_segment_signal(direction: defines.rail_direction, in_else_out: boolean) -> LuaEntity?`
- Get the rail signal at the start/end of the rail segment this rail is in.  A rail segment is a continuous section of rail with no branches, signals, nor train stops.
- **Restriction:** Can only be used if this is: **Rail**

### `get_rail_segment_stop(direction: defines.rail_direction) -> LuaEntity?`
- Get train stop at the start/end of the rail segment this rail is in.  A rail segment is a continuous section of rail with no branches, signals, nor train stops.
- **Restriction:** Can only be used if this is: **Rail**

### `get_recipe() -> LuaRecipe?, LuaQualityPrototype?`
- Current recipe being assembled by this machine, if any.
- **Restriction:** Can only be used if this is: **CraftingMachine**

### `get_signal(extra_wire_connector_id?: defines.wire_connector_id, signal: SignalID, wire_connector_id: defines.wire_connector_id) -> int32`
- Read a single signal from the selected wire connector

### `get_signals(extra_wire_connector_id?: defines.wire_connector_id, wire_connector_id: defines.wire_connector_id) -> Array<Signal>?`
- Read all signals from the selected wire connector.

### `get_spider_legs() -> Array<LuaEntity>`
- Gets legs of given SpiderVehicle.
- **Restriction:** Can only be used if this is: **SpiderVehicle**

### `get_stopped_train() -> LuaTrain?`
- The train currently stopped at this train stop, if any.
- **Restriction:** Can only be used if this is: **TrainStop**

### `get_train_stop_trains() -> Array<LuaTrain>`
- The trains scheduled to stop at this train stop.
- **Restriction:** Can only be used if this is: **TrainStop**

### `get_transport_line(index: uint32) -> LuaTransportLine`
- Get a transport line of a belt or belt connectable entity.
- **Restriction:** Can only be used if this is: **TransportBeltConnectable**

### `get_upgrade_target() -> LuaEntityPrototype?, LuaQualityPrototype?`
- Returns the new entity prototype and its quality.

### `get_wire_connector(or_create: boolean, wire_connector_id: defines.wire_connector_id) -> LuaWireConnector`
- Gets a single wire connector of this entity

### `get_wire_connectors(or_create: boolean) -> Dict<defines.wire_connector_id, LuaWireConnector>`
- Gets all wire connectors of this entity

### `ghost_has_flag(flag: EntityPrototypeFlag) -> boolean`
- Same as [LuaEntity::has_flag](runtime:LuaEntity::has_flag), but targets the inner entity on a entity ghost.
- **Restriction:** Can only be used if this is: **EntityGhost**

### `has_flag(flag: EntityPrototypeFlag) -> boolean`
- Test whether this entity's prototype has a certain flag set.  `entity.has_flag(f)` is a shortcut for `entity.prototype.has_flag(f)`.

### `insert_fluid(fluid: Fluid) -> double`
- Insert fluid into this entity. Fluidbox is chosen automatically.

### `inventory_supports_bar(inventory_index: defines.inventory) -> boolean`
- The same as [LuaInventory::supports_bar](runtime:LuaInventory::supports_bar) but also works for ghosts where the inventory is not available through [LuaControl::get_inventory](runtime:LuaControl::get_inventory).

### `inventory_supports_filters(inventory_index: defines.inventory) -> boolean`
- The same as [LuaInventory::supports_filters](runtime:LuaInventory::supports_filters) but also works for ghosts where the inventory is not available through [LuaControl::get_inventory](runtime:LuaControl::get_inventory).

### `is_closed() -> boolean`
- 
- **Restriction:** Can only be used if this is: **Gate**

### `is_closing() -> boolean`
- 
- **Restriction:** Can only be used if this is: **Gate**

### `is_connected_to_electric_network() -> boolean`
- Returns `true` if this entity produces or consumes electricity and is connected to an electric network that has at least one entity that can produce power.

### `is_crafting() -> boolean`
- Returns whether a craft is currently in process. It does not indicate whether progress is currently being made, but whether a crafting process has been started in this machine.
- **Restriction:** Can only be used if this is: **CraftingMachine**

### `is_inventory_filtered(inventory_index: defines.inventory) -> boolean`
- The same as [LuaInventory::is_filtered](runtime:LuaInventory::is_filtered) but also works for ghosts where the inventory is not available through [LuaControl::get_inventory](runtime:LuaControl::get_inventory).

### `is_opened() -> boolean`
- 
- **Restriction:** Can only be used if this is: **Gate**

### `is_opening() -> boolean`
- 
- **Restriction:** Can only be used if this is: **Gate**

### `is_rail_in_same_rail_block_as(other_rail: LuaEntity) -> boolean`
- Checks if this rail and other rail both belong to the same rail block.
- **Restriction:** Can only be used if this is: **Rail**

### `is_rail_in_same_rail_segment_as(other_rail: LuaEntity) -> boolean`
- Checks if this rail and other rail both belong to the same rail segment.
- **Restriction:** Can only be used if this is: **Rail**

### `is_registered_for_construction() -> boolean`
- Is this entity or tile ghost or item request proxy registered for construction? If false, it means a construction robot has been dispatched to build the entity, or it is not an entity that can be constructed.

### `is_registered_for_deconstruction(force: ForceID) -> boolean`
- Is this entity registered for deconstruction with this force? If false, it means a construction robot has been dispatched to deconstruct it, or it is not marked for deconstruction. The complexity is effectively O(1) - it depends on the number of objects targeting this entity which should be small enough.

### `is_registered_for_repair() -> boolean`
- Is this entity registered for repair? If false, it means a construction robot has been dispatched to repair it, or it is not damaged. This is worst-case O(N) complexity where N is the current number of things in the repair queue.

### `is_registered_for_upgrade() -> boolean`
- Is this entity registered for upgrade? If false, it means a construction robot has been dispatched to upgrade it, or it is not marked for upgrade. This is worst-case O(N) complexity where N is the current number of things in the upgrade queue.

### `launch_rocket(character?: LuaEntity, destination?: CargoDestination) -> boolean`
- 
- **Restriction:** Can only be used if this is: **RocketSilo**

### `mine(force?: boolean, ignore_minable?: boolean, inventory?: LuaInventory, raise_destroyed?: boolean) -> boolean`
- Mines this entity.  'Standard' operation is to keep calling `LuaEntity.mine` with an inventory until all items are transferred and the items dealt with.  The result of mining the entity (the item(s) it produces when mined) will be dropped on the ground if they don't fit into the provided inventory. If no inventory is provided, the items will be destroyed.

### `order_deconstruction(force: ForceID, player?: PlayerIdentification, undo_index?: uint32) -> boolean`
- Sets the entity to be deconstructed by construction robots.

### `order_upgrade(force: ForceID, player?: PlayerIdentification, target: EntityWithQualityID, undo_index?: uint32) -> boolean`
- Sets the entity to be upgraded by construction robots.

### `play_note(instrument: uint32, note: uint32, stop_playing_sounds?: boolean) -> boolean`
- Plays a note with the given instrument and note.
- **Restriction:** Can only be used if this is: **ProgrammableSpeaker**

### `register_tree(tree: LuaEntity) -> boolean`
- Registers the given tree in this agricultural tower.  If the tree is not within range of the tower it will not be registered.  If the tree is already registered with a tower it will not be registered.
- **Restriction:** Can only be used if this is: **AgriculturalTower**

### `release_from_spawner()`
- Release the unit from the spawner which spawned it. This allows the spawner to continue spawning additional units.
- **Restriction:** Can only be used if this is: **Unit, SpiderUnit**

### `remove_fluid(amount: double, maximum_temperature?: double, minimum_temperature?: double, name: string, temperature?: double) -> double`
- Remove fluid from this entity.  If temperature is given only fluid matching that exact temperature is removed. If minimum and maximum is given fluid within that range is removed.

### `remove_market_item(offer: uint32) -> boolean`
- Remove an offer from a market.  The other offers are moved down to fill the gap created by removing the offer, which decrements the overall size of the offer array.
- **Restriction:** Can only be used if this is: **Market**

### `request_to_close(force: ForceID)`
- 
- **Restriction:** Can only be used if this is: **Gate**

### `request_to_open(extra_time?: uint32, force: ForceID)`
- 
- **Restriction:** Can only be used if this is: **Gate**

### `revive(overflow?: LuaInventory, raise_revive?: boolean) -> Dict<string, uint32>?, LuaEntity?, LuaEntity?`
- Revive a ghost, which turns it from a ghost into a real entity or tile.
- **Restriction:** Can only be used if this is: **Ghost**

### `rotate(by_player?: PlayerIdentification, reverse?: boolean) -> boolean`
- Rotates this entity as if the player rotated it.

### `set_beam_source(source: LuaEntity | MapPosition)`
- Set the source of this beam.
- **Restriction:** Can only be used if this is: **Beam**

### `set_beam_target(target: LuaEntity | MapPosition)`
- Set the target of this beam.
- **Restriction:** Can only be used if this is: **Beam**

### `set_driver(driver: LuaEntity | PlayerIdentification | nil)`
- Sets the driver of this vehicle.  This differs from [LuaEntity::set_passenger](runtime:LuaEntity::set_passenger) in that the passenger can't drive the vehicle.
- **Restriction:** Can only be used if this is: **Vehicle**

### `set_filter(filter?: ItemFilter | ItemWithQualityID | EntityID | AsteroidChunkID, index: uint32)`
- Set the filter for a slot in an inserter (ItemFilter), loader (ItemFilter), mining drill (EntityID), asteroid collector (AsteroidChunkID) or logistic storage container (ItemWithQualityID). The entity must allow filters.

### `set_fluid(fluid?: Fluid, index: uint32) -> Fluid?`
- Sets fluid to the index-th fluid storage. This includes fluidbox and non-fluidbox fluid storages like fluid wagon contents. Refer to [LuaEntity::fluids_count](runtime:LuaEntity::fluids_count) for more information on available storages.  Fluid storages that are part of fluidboxes (also available through [LuaFluidBox](runtime:LuaFluidBox)) may reject some fluids if they do not match filters or are above the fluidbox volume. To verify how much fluid was set a return value can be used which is the same as value that would be returned by [LuaEntity::get_fluid](runtime:LuaEntity::get_fluid).

### `set_heat_setting(filter: HeatSetting)`
- Sets the heat setting for this heat interface.
- **Restriction:** Can only be used if this is: **HeatInterface**

### `set_infinity_container_filter(filter: InfinityInventoryFilter | nil, index: uint32)`
- Sets the filter for this infinity container at the given index.
- **Restriction:** Can only be used if this is: **InfinityContainer, InfinityCargoWagon**

### `set_infinity_pipe_filter(filter: InfinityPipeFilter | nil)`
- Sets the filter for this infinity pipe.
- **Restriction:** Can only be used if this is: **InfinityPipe**

### `set_inventory_bar(bar?: uint32, inventory_index: defines.inventory)`
- The same as [LuaInventory::set_bar](runtime:LuaInventory::set_bar) but also works for ghosts where the inventory is not available through [LuaControl::get_inventory](runtime:LuaControl::get_inventory).

### `set_inventory_filter(filter: ItemFilter | nil, index: uint32, inventory_index: defines.inventory) -> boolean`
- The same as [LuaInventory::set_filter](runtime:LuaInventory::set_filter) but also works for ghosts where the inventory is not available through [LuaControl::get_inventory](runtime:LuaControl::get_inventory).

### `set_inventory_size_override(inventory_index: defines.inventory, overflow?: LuaInventory, size_override: uint16 | nil)`
- Sets inventory size override. When set, supported entity will ignore inventory size from prototype and will instead keep inventory size equal to the override. Setting `nil` will restore default inventory size.
- **Restriction:** Can only be used if this is: **ContainerEntity, CargoWagon**

### `set_movement(direction: Vector, speed: double)`
- Sets the movement direction and movement speed for this combat robot or asteroid.  Note that for combat robots this does not affect the constant drift in the direction they are facing.
- **Restriction:** Can only be used if this is: **CombatRobot, Asteroid**

### `set_passenger(passenger: LuaEntity | PlayerIdentification | nil)`
- Sets the passenger of this car, spidertron, or cargo pod.  This differs from [LuaEntity::get_driver](runtime:LuaEntity::get_driver) in that the passenger can't drive the car.
- **Restriction:** Can only be used if this is: **Car, SpiderVehicle, CargoPod**

### `set_priority_target(entity_id?: EntityID, index: uint32)`
- Set the entity ID name at the specified position in the turret's priority list.

### `set_recipe(quality?: QualityID, recipe?: RecipeID) -> ItemWithQualityCounts`
- Sets the given recipe in this assembly machine.
- **Restriction:** Can only be used if this is: **AssemblingMachine**

### `silent_revive(overflow?: LuaInventory, raise_revive?: boolean) -> ItemWithQualityCounts, LuaEntity?, LuaEntity?`
- Revives a ghost silently, so the revival makes no sound and no smoke is created.
- **Restriction:** Can only be used if this is: **Ghost**

### `spawn_decorations()`
- Triggers spawn_decoration actions defined in the entity prototype or does nothing if entity is not "turret" or "unit-spawner".

### `start_fading_out()`
- Only works if the entity is a speech-bubble, with an "effect" defined in its wrapper_flow_style. Starts animating the opacity of the speech bubble towards zero, and destroys the entity when it hits zero.
- **Restriction:** Can only be used if this is: **SpeechBubble**

### `stop_spider()`
- Sets the [speed](runtime:LuaEntity::speed) of the given SpiderVehicle to zero. Notably does not clear its [autopilot_destination](runtime:LuaEntity::autopilot_destination), which it will continue moving towards if set.
- **Restriction:** Can only be used if this is: **SpiderVehicle**

### `supports_backer_name() -> boolean`
- Whether this entity supports a backer name.

### `to_be_deconstructed() -> boolean`
- Is this entity marked for deconstruction?

### `to_be_upgraded() -> boolean`
- Is this entity marked for upgrade?

### `toggle_equipment_movement_bonus()`
- Toggle this entity's equipment movement bonus. Does nothing if the entity does not have an equipment grid.  This property can also be read and written on the equipment grid of this entity.

### `update_connections()`
- Reconnect loader, beacon, cliff and mining drill connections to entities that might have been teleported out or in by the script. The game doesn't do this automatically as we don't want to lose performance by checking this in normal games.
