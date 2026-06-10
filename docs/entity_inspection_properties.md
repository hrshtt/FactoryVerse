# Entity Inspection Properties Reference

This document defines the properties to extract for each entity category during inspection. This serves as the source of truth for implementing `inspection.lua`.

All categories include base properties:
- `entity_name`: string - Entity prototype name
- `entity_type`: string - Entity type
- `position`: {x: number, y: number} - Entity position
- `direction`: number - Entity direction (0-255, or defines.direction enum)
- `tick`: number - Game tick when inspection was taken
- `health`: number? - Current health (if entity has health)
- `max_health`: number? - Maximum health (if entity has health)
- `status`: string? - Entity status (working, no-power, etc.) User Comments: send back enum

---

## CraftingMachine

Entities: `assembling-machine`, `furnace`, `chemical-plant`, `oil-refinery`, `centrifuge`, `rocket-silo`

- `recipe`: string | null - Current recipe name (from `entity.get_recipe()`)
- `crafting_progress`: number | null - Crafting progress 0.0-1.0 (from `entity.crafting_progress`)
- `bonus_progress`: number | null - Productivity bonus progress 0.0-1.0 (from `entity.bonus_progress`)
- `is_crafting`: boolean | null - Whether currently crafting (from `entity.is_crafting()`)
- `input`: {[item_name: string]: number} | null - Input inventory contents
- `output`: {[item_name: string]: number} | null - Output inventory contents
- `modules`: {[item_name: string]: number} | null - Module inventory contents (if applicable)
- `fuel`: {[item_name: string]: number} | null - Fuel inventory contents (furnaces only)
- `energy`: {current: number, capacity: number} | null - Electric energy state (if electric)
- `beacons_count`: number | null - Number of beacons affecting this entity (from `entity.beacons_count`)
- ~~`productivity_bonus`: number | null - Total productivity bonus (from `entity.productivity_bonus`)~~
- ~~`speed_bonus`: number | null - Speed bonus from modules/beacons (from `entity.speed_bonus`)~~
- ~~`consumption_bonus`: number | null - Consumption bonus (from `entity.consumption_bonus`)~~
- ~~`effects`: table | null - Applied effects table (from `entity.effects`)~~

```json
{
  "recipe": "string | null",
  "crafting_progress": "number | null",
  "bonus_progress": "number | null",
  "is_crafting": "boolean | null",
  "input": "{ [item_name: string]: number } | null",
  "output": "{ [item_name: string]: number } | null",
  "modules": "{ [item_name: string]: number } | null",
  "fuel": "{ [item_name: string]: number } | null",
  "energy": "{ current: number, capacity: number } | null",
  "beacons_count": "number | null",
}
```

### Furnace

Additional properties for furnaces:

- `burner`: BurnerData | null - Burner state (furnaces, burner entities)
- `previous_recipe`: string | null - Previous recipe (from `entity.previous_recipe`)

```json
{
  "burner": "BurnerData | null",
  "previous_recipe": "string | null"
}
```

### RocketSilo

Additional properties for rocket silos:

- `rocket_parts`: number | null - Number of rocket parts in silo (from `entity.rocket_parts`)
- `rocket_silo_status`: string | null - Rocket silo status (from `entity.rocket_silo_status`)
- ~~`transitional_request_target`: string | null - Space platform being requested for (from `entity.transitional_request_target`)~~
- ~~`use_transitional_requests`: boolean | null - Whether using transitional requests (from `entity.use_transitional_requests`)~~

```json
{
  "rocket_parts": "number | null",
  "rocket_silo_status": "string | null",
  "transitional_request_target": "string | null",
  "use_transitional_requests": "boolean | null"
}
```

---

## MiningDrill

Entities: `mining-drill` (both burner and electric variants)

- `mining_target`: MiningTargetData | null - Resource being mined (from `entity.mining_target`)
- `mining_progress`: number | null - Mining progress (0 to mining_time) (from `entity.mining_progress`)
- `bonus_mining_progress`: number | null - Bonus mining progress (from `entity.bonus_mining_progress`)
- `output`: {[item_name: string]: number} | null - Output inventory contents (from `entity.get_output_inventory()`)
- `drop_position`: {x: number, y: number} - Position where items are dropped (from `entity.drop_position`)
- `drop_target`: EntityRef | null - Target entity receiving items (from `entity.drop_target`)
- `mining_area`: BoundingBox | null - Mining area box (from `entity.mining_area`)
- `energy`: {current: number, capacity: number} | null - Electric energy state (electric drills)
- `burner`: BurnerData | null - Burner state (burner mining drills)
- `mining_drill_filter_mode`: string | null - Filter mode (from `entity.mining_drill_filter_mode`)

```json
{
  "mining_target": {
    "name": "string",
    "type": "string",
    "position": { "x": "number", "y": "number" },
    "amount": "number"
  } | null,
  "mining_progress": "number | null",
  "bonus_mining_progress": "number | null",
  "output": "{ [item_name: string]: number } | null",
  "drop_position": { "x": "number", "y": "number" },
  "drop_target": {
    "name": "string",
    "position": { "x": "number", "y": "number" }
  } | null,
  "mining_area": "BoundingBox | null",
  "energy": { "current": "number", "capacity": "number" } | null,
  "burner": "BurnerData | null",
  "mining_drill_filter_mode": "string | null"
}
```

---

## Inserter

Entities: `inserter`, `fast-inserter`, `long-handed-inserter`, `filter-inserter`, `stack-inserter`, `stack-filter-inserter`, `burner-inserter`

- `held_item`: {name: string, count: number} | null - Currently held item (from `entity.held_stack`)
- `held_stack_position`: {x: number, y: number} | null - Position of inserter hand (from `entity.held_stack_position`)
- `pickup_position`: {x: number, y: number} - Pickup position (from `entity.pickup_position`)
- `drop_position`: {x: number, y: number} - Drop position (from `entity.drop_position`)
- `pickup_target`: EntityRef | null - Source entity (from `entity.pickup_target`)
- `drop_target`: EntityRef | null - Destination entity (from `entity.drop_target`)
- `inserter_filter_mode`: string | null - Filter mode (from `entity.inserter_filter_mode`)
- `filter_slot_count`: number | null - Number of filter slots (from `entity.filter_slot_count`)
- `filters`: {[index: number]: string} | null - Filter items by slot index (from `entity.get_filter(index)`)
- `inserter_stack_size_override`: number | null - Stack size override (from `entity.inserter_stack_size_override`)
- `inserter_target_pickup_count`: number | null - Target pickup count (from `entity.inserter_target_pickup_count`)
- `pickup_from_left_lane`: boolean | null - Can pick from left lane (from `entity.pickup_from_left_lane`)
- `pickup_from_right_lane`: boolean | null - Can pick from right lane (from `entity.pickup_from_right_lane`)
- `inserter_spoil_priority`: string | null - Spoil priority (from `entity.inserter_spoil_priority`)
- `use_filters`: boolean | null - Whether using filters (from `entity.use_filters`)

```json
{
  "held_item": { "name": "string", "count": "number" } | null,
  "held_stack_position": { "x": "number", "y": "number" } | null,
  "pickup_position": { "x": "number", "y": "number" },
  "drop_position": { "x": "number", "y": "number" },
  "pickup_target": {
    "name": "string",
    "position": { "x": "number", "y": "number" }
  } | null,
  "drop_target": {
    "name": "string",
    "position": { "x": "number", "y": "number" }
  } | null,
  "inserter_filter_mode": "string | null",
  "filter_slot_count": "number | null",
  "filters": "{ [index: number]: string } | null",
  "inserter_stack_size_override": "number | null",
  "inserter_target_pickup_count": "number | null",
  "pickup_from_left_lane": "boolean | null",
  "pickup_from_right_lane": "boolean | null",
  "inserter_spoil_priority": "string | null",
  "use_filters": "boolean | null"
}
```

---

## Container

Entities: `container`, `logistic-container`, `cargo-wagon`

- `contents`: {[item_name: string]: number} | null - Inventory contents (from `entity.get_inventory(defines.inventory.chest)` or `defines.inventory.cargo_wagon`)
- `inventory_bar`: number | null - Bar limit (from `entity.get_inventory(...).get_bar()`)
- `inventory_size_override`: number | null - Inventory size override (from `entity.get_inventory_size_override()`)
- `storage_filter`: string | null - Storage filter (storage containers only) (from `entity.storage_filter`)
- `filter_slot_count`: number | null - Number of filter slots (from `entity.filter_slot_count`)
- `filters`: {[index: number]: string} | null - Filter items by slot index (from `entity.get_filter(index)`)
- `request_from_buffers`: boolean | null - Request from buffers (from `entity.request_from_buffers`)

```json
{
  "contents": "{ [item_name: string]: number } | null",
  "inventory_bar": "number | null",
  "inventory_size_override": "number | null",
  "storage_filter": "string | null",
  "filter_slot_count": "number | null",
  "filters": "{ [index: number]: string } | null",
  "request_from_buffers": "boolean | null"
}
```

---

## TransportBelt

Entities: `transport-belt`, `fast-transport-belt`, `express-transport-belt`, `underground-belt`, `splitter`, `lane-splitter`

- `belt_shape`: string | null - Current belt shape (from `entity.belt_shape`)
- `belt_neighbours`: EntityRef[] | null - Connected belts (from `entity.belt_neighbours`)
- `linked_belt_neighbour`: EntityRef | null - Linked belt neighbour (from `entity.linked_belt_neighbour`)
- `linked_belt_type`: string | null - Linked belt type (from `entity.linked_belt_type`)
- `belt_to_ground_type`: string | null - Underground belt type: "input" or "output" (from `entity.belt_to_ground_type`)
- `splitter_filter`: string | null - Splitter filter (from `entity.splitter_filter`)
- `splitter_input_priority`: string | null - Input priority (from `entity.splitter_input_priority`)
- `splitter_output_priority`: string | null - Output priority (from `entity.splitter_output_priority`)
- `transport_lines`: TransportLineData[] | null - Transport line contents (from `entity.get_transport_line(index)`)

```json
{
  "belt_shape": "string | null",
  "belt_neighbours": [
    {
      "name": "string",
      "position": { "x": "number", "y": "number" }
    }
  ] | null,
  "linked_belt_neighbour": {
    "name": "string",
    "position": { "x": "number", "y": "number" }
  } | null,
  "linked_belt_type": "string | null",
  "belt_to_ground_type": "string | null",
  "splitter_filter": "string | null",
  "splitter_input_priority": "string | null",
  "splitter_output_priority": "string | null",
  "transport_lines": [
    {
      "index": "number",
      "contents": "{ [item_name: string]: number }"
    }
  ] | null
}
```

---

## Lab

Entities: `lab`

- `input`: {[item_name: string]: number} | null - Science pack inventory (from `entity.get_inventory(defines.inventory.lab_input)`)
- `modules`: {[item_name: string]: number} | null - Module inventory (from `entity.get_inventory(defines.inventory.lab_modules)`)
- `current_research`: string | null - Currently researching technology name (from `entity.force.research_queue`)
- `productivity_bonus`: number | null - Productivity bonus (from `entity.productivity_bonus`)
- `speed_bonus`: number | null - Speed bonus (from `entity.speed_bonus`)
- `beacons_count`: number | null - Number of beacons affecting this (from `entity.beacons_count`)
- `effects`: table | null - Applied effects (from `entity.effects`)
- `energy`: {current: number, capacity: number} | null - Electric energy state (from `entity.energy`)

```json
{
  "input": "{ [item_name: string]: number } | null",
  "modules": "{ [item_name: string]: number } | null",
  "current_research": "string | null",
  "productivity_bonus": "number | null",
  "speed_bonus": "number | null",
  "beacons_count": "number | null",
  "effects": "table | null",
  "energy": { "current": "number", "capacity": "number" } | null
}
```

---

## EnergyProducer

Entities: `boiler`, `steam-engine`, `steam-turbine`, `solar-panel`, `nuclear-reactor`

- `energy_generated_last_tick`: number | null - Energy generated last tick (from `entity.energy_generated_last_tick`)
- `power_production`: number | null - Power production (from `entity.power_production`)
- `burner`: BurnerData | null - Burner state (boilers) (from `entity.burner`)
- `temperature`: number | null - Temperature (reactors, heat pipes) (from `entity.temperature`)
- `heat_neighbours`: EntityRef[] | null - Heat-connected neighbours (from `entity.heat_neighbours`)
- `neighbour_bonus`: number | null - Reactor neighbour bonus (from `entity.neighbour_bonus`)
- `energy`: {current: number, capacity: number} | null - Energy buffer (if applicable) (from `entity.energy`)

```json
{
  "energy_generated_last_tick": "number | null",
  "power_production": "number | null",
  "burner": "BurnerData | null",
  "temperature": "number | null",
  "heat_neighbours": [
    {
      "name": "string",
      "position": { "x": "number", "y": "number" }
    }
  ] | null,
  "neighbour_bonus": "number | null",
  "energy": { "current": "number", "capacity": "number" } | null
}
```

---

## ElectricPole

Entities: `small-electric-pole`, `medium-electric-pole`, `big-electric-pole`, `substation`

- `electric_network_id`: number | null - Electric network ID (from `entity.electric_network_id`)
- `is_connected`: boolean - Whether connected to electric network (from `entity.is_connected_to_electric_network()`)
- `electric_network_statistics`: {input_count: number, output_count: number} | null - Network statistics (from `entity.electric_network_statistics`)
- `energy`: {current: number, capacity: number} | null - Energy buffer (if applicable) (from `entity.energy`)

```json
{
  "electric_network_id": "number | null",
  "is_connected": "boolean",
  "electric_network_statistics": {
    "input_count": "number",
    "output_count": "number"
  } | null,
  "energy": { "current": "number", "capacity": "number" } | null
}
```

---

## Beacon

Entities: `beacon`

- `modules`: {[item_name: string]: number} | null - Module inventory (from `entity.get_inventory(defines.inventory.beacon_modules)`)
- `effects`: table | null - Effects being broadcast (from `entity.effects`)
- `energy`: {current: number, capacity: number} | null - Electric energy state (from `entity.energy`)
- `get_beacon_effect_receivers`: EntityRef[] | null - Entities affected by this beacon (from `entity.get_beacon_effect_receivers()`)

```json
{
  "modules": "{ [item_name: string]: number } | null",
  "effects": "table | null",
  "energy": { "current": "number", "capacity": "number" } | null,
  "get_beacon_effect_receivers": [
    {
      "name": "string",
      "position": { "x": "number", "y": "number" }
    }
  ] | null
}
```

---

~~## Turret~~ NotImplemented

Entities: `turret`, `gun-turret`, `laser-turret`, `flamethrower-turret`, `artillery-turret`

- `damage_dealt`: number | null - Total damage dealt (from `entity.damage_dealt`)
- `kills`: number | null - Number of units killed (from `entity.kills`)
- `shooting_target`: EntityRef | null - Current shooting target (from `entity.shooting_target`)
- `priority_targets`: string[] | null - Priority target entity IDs (from `entity.priority_targets`)
- `ignore_unprioritised_targets`: boolean | null - Ignore non-priority targets (from `entity.ignore_unprioritised_targets`)
- `artillery_auto_targeting`: boolean | null - Auto-targeting enabled (artillery only) (from `entity.artillery_auto_targeting`)
- `energy`: {current: number, capacity: number} | null - Electric energy state (laser turrets) (from `entity.energy`)

```json
{
  "damage_dealt": "number | null",
  "kills": "number | null",
  "shooting_target": {
    "name": "string",
    "position": { "x": "number", "y": "number" }
  } | null,
  "priority_targets": "string[] | null",
  "ignore_unprioritised_targets": "boolean | null",
  "artillery_auto_targeting": "boolean | null",
  "energy": { "current": "number", "capacity": "number" } | null
}
```

---

## Pump

Entities: `pump`, `offshore-pump`

- `pumped_last_tick`: number | null - Amount of fluid moved last tick (from `entity.pumped_last_tick`)
- `pump_rail_target`: EntityRef | null - Rail target (pumps only) (from `entity.pump_rail_target`)
- `fluidbox`: FluidBoxData[] | null - Fluidbox contents (from `entity.fluidbox`)
- `get_fluid_source_fluid`: string | null - Expected fluid from source tile (offshore pumps only) (from `entity.get_fluid_source_fluid()`)
- `get_fluid_source_tile`: {x: number, y: number} | null - Source tile position (offshore pumps only) (from `entity.get_fluid_source_tile()`)

```json
{
  "pumped_last_tick": "number | null",
  "pump_rail_target": {
    "name": "string",
    "position": { "x": "number", "y": "number" }
  } | null,
  "fluidbox": [
    {
      "name": "string",
      "amount": "number",
      "temperature": "number"
    }
  ] | null,
  "get_fluid_source_fluid": "string | null",
  "get_fluid_source_tile": { "x": "number", "y": "number" } | null
}
```

---

## Radar

Entities: `radar`

- `radar_scan_progress`: number | null - Current scan progress 0.0-1.0 (from `entity.radar_scan_progress`)
- `energy`: {current: number, capacity: number} | null - Electric energy state (from `entity.energy`)

```json
{
  "radar_scan_progress": "number | null",
  "energy": { "current": "number", "capacity": "number" } | null
}
```

---

## Lamp

~~Entities: `lamp`~~ NotImplemented

- `always_on`: boolean | null - Always on when not driven by control behavior (from `entity.always_on`)
- `energy`: {current: number, capacity: number} | null - Electric energy state (from `entity.energy`)

```json
{
  "always_on": "boolean | null",
  "energy": { "current": "number", "capacity": "number" } | null
}
```

---

## Accumulator

Entities: `accumulator`

- `energy`: {current: number, capacity: number} | null - Stored energy (from `entity.energy`)
- `electric_network_id`: number | null - Electric network ID (from `entity.electric_network_id`)

```json
{
  "energy": { "current": "number", "capacity": "number" } | null,
  "electric_network_id": "number | null"
}
```

---

~~## HeatPipe~~ NotImplemented

Entities: `heat-pipe`

- `temperature`: number | null - Current temperature (from `entity.temperature`)
- `heat_neighbours`: EntityRef[] | null - Heat-connected neighbours (from `entity.heat_neighbours`)

```json
{
  "temperature": "number | null",
  "heat_neighbours": [
    {
      "name": "string",
      "position": { "x": "number", "y": "number" }
    }
  ] | null
}
```

---

~~## Combinator~~ NotImplemented

Entities: `arithmetic-combinator`, `decider-combinator`, `constant-combinator`, `selector-combinator`

- `combinator_description`: string | null - Description on combinator (from `entity.combinator_description`)
- `get_control_behavior`: ControlBehaviorData | null - Control behavior data (from `entity.get_control_behavior()`)

```json
{
  "combinator_description": "string | null",
  "get_control_behavior": "ControlBehaviorData | null"
}
```

---

~~## ProgrammableSpeaker~~ NotImplemented

Entities: `programmable-speaker`

- `alert_parameters`: table | null - Alert parameters (from `entity.alert_parameters`)
- `parameters`: table | null - Speaker parameters (from `entity.parameters`)

```json
{
  "alert_parameters": "table | null",
  "parameters": "table | null"
}
```

---

~~## TrainStop~~ NotImplemented

Entities: `train-stop`

- `backer_name`: string | null - Train stop name (from `entity.backer_name`)
- `connected_rail`: EntityRef | null - Connected rail entity (from `entity.connected_rail`)
- `connected_rail_direction`: number | null - Rail direction (from `entity.connected_rail_direction`)
- `train_stop_priority`: string | null - Priority (from `entity.train_stop_priority`)
- `trains_limit`: number | null - Train limit (from `entity.trains_limit`)
- `trains_count`: number | null - Number of trains related to this stop (from `entity.trains_count`)
- `get_stopped_train`: EntityRef | null - Currently stopped train (from `entity.get_stopped_train()`)
- `get_train_stop_trains`: EntityRef[] | null - Trains scheduled to stop (from `entity.get_train_stop_trains()`)

```json
{
  "backer_name": "string | null",
  "connected_rail": {
    "name": "string",
    "position": { "x": "number", "y": "number" }
  } | null,
  "connected_rail_direction": "number | null",
  "train_stop_priority": "string | null",
  "trains_limit": "number | null",
  "trains_count": "number | null",
  "get_stopped_train": {
    "name": "string",
    "position": { "x": "number", "y": "number" }
  } | null,
  "get_train_stop_trains": [
    {
      "name": "string",
      "position": { "x": "number", "y": "number" }
    }
  ] | null
}
```

---

## ResourceEntity

Entities: `resource` (iron-ore, copper-ore, stone, coal, etc.)

- `amount`: number - Remaining resource amount (from `entity.amount`)
- `initial_amount`: number | null - Initial amount (infinite resources) (from `entity.initial_amount`)

```json
{
  "amount": "number",
  "initial_amount": "number | null"
}
```

---

## ~~GenericEntity~~

Entities: Any entity type not covered by specific categories above

- `energy`: {current: number, capacity: number} | null - Energy state (if applicable) (from `entity.energy`)
- `burner`: BurnerData | null - Burner state (if applicable) (from `entity.burner`)
- `active`: boolean | null - Whether entity is active (from `entity.active`)

```json
{
  "energy": { "current": "number", "capacity": "number" } | null,
  "burner": "BurnerData | null",
  "active": "boolean | null"
}
```

---

## Shared Data Types

### BurnerData

Properties extracted from `entity.burner`:

- `heat`: number | null - Current heat (from `burner.heat`)
- `heat_capacity`: number | null - Heat capacity (from `burner.heat_capacity`)
- `remaining_burning_fuel`: number | null - Remaining fuel energy (from `burner.remaining_burning_fuel`)
- `currently_burning`: string | null - Currently burning item name (from `burner.currently_burning.name`)
- `burning_progress`: number | null - Calculated: 1.0 - (remaining_burning_fuel / fuel_energy)

```json
{
  "heat": "number | null",
  "heat_capacity": "number | null",
  "remaining_burning_fuel": "number | null",
  "currently_burning": "string | null",
  "burning_progress": "number | null"
}
```

### EntityRef

Reference to another entity:

- `name`: string - Entity prototype name
- `position`: {x: number, y: number} - Entity position

```json
{
  "name": "string",
  "position": { "x": "number", "y": "number" }
}
```

### BoundingBox

Bounding box structure:

- `left_top`: {x: number, y: number}
- `right_bottom`: {x: number, y: number}

```json
{
  "left_top": { "x": "number", "y": "number" },
  "right_bottom": { "x": "number", "y": "number" }
}
```

### FluidBoxData

Fluid box contents:

- `name`: string - Fluid name
- `amount`: number - Fluid amount
- `temperature`: number - Fluid temperature

```json
{
  "name": "string",
  "amount": "number",
  "temperature": "number"
}
```

### TransportLineData

Transport line contents:

- `index`: number - Line index
- `contents`: {[item_name: string]: number} - Items on this line

```json
{
  "index": "number",
  "contents": "{ [item_name: string]: number }"
}
```

### MiningTargetData

Mining target information:

- `name`: string - Resource prototype name
- `type`: string - Resource type
- `position`: {x: number, y: number} - Resource position
- `amount`: number - Remaining resource amount

```json
{
  "name": "string",
  "type": "string",
  "position": { "x": "number", "y": "number" },
  "amount": "number"
}
```

