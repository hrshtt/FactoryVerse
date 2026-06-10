# Placement Hints - Design Questions for Partially Implemented Features

This document contains design questions to help implement the remaining connection types and features in the placement hints module.

## Partially Implemented Features

### 1. INSERTER_REACH Connection Type

**Current Status**: Method `get_inserter_placement_positions()` exists but is not integrated into `get_connection_positions()` with `ConnectionType.INSERTER_REACH`.

**Questions**:

1. **API Design**:
   - Should `get_connection_positions()` with `INSERTER_REACH` accept both `source_entity` and `target_entity` as parameters?
   - Or should it work like other connection types (only `source_entity` + `target_entity_name`)?
   - Current method signature: `get_inserter_placement_positions(source_entity, target_entity, inserter_name)`
   - Proposed: `get_connection_positions(source_entity, target_entity, ConnectionType.INSERTER_REACH, inserter_name="inserter")`

2. **Inserter Types**:
   - Should the method support all inserter types (inserter, long-handed-inserter, fast-inserter, stack-inserter, etc.)?
   - Do different inserter types have different reach distances that need to be considered?
   - Should we validate that the inserter can actually reach both source and target?

3. **Direction Handling**:
   - Should the method return positions with specific directions for the inserter?
   - Or should it try all 4 cardinal directions and return all valid positions?
   - Current implementation tries all 4 directions - is this the desired behavior?

4. **Validation**:
   - Should we validate that the inserter can actually pick up from source and drop to target?
   - Or just validate that the inserter can be placed at the position?
   - Factorio has `inserter.can_place()` - should we use this?

5. **Return Type**:
   - Current method returns `List[Tuple[MapPosition, Direction]]`
   - Should it return `List[ConnectionPosition]` to match other connection types?
   - What should `perpendicular_offset` mean for inserters? (alignment metric)

### 2. BELT_FLOW Connection Type

**Current Status**: Not implemented.

**Questions**:

1. **Use Case**:
   - What is the primary use case for BELT_FLOW?
   - Is it: "Given a belt at position X, where can I place another belt to continue the flow?"
   - Or: "Given two belts, where can I place a belt to connect them?"

2. **Belt Types**:
   - Should it support all belt types (transport-belt, fast-transport-belt, express-transport-belt)?
   - Do underground belts need special handling?
   - What about splitter connections?

3. **Direction Requirements**:
   - Belts have strict direction requirements - how should we handle this?
   - Should we return positions with specific directions?
   - How do we ensure the belt flow direction is correct?

4. **Algorithm**:
   - Should we calculate positions based on belt's output position?
   - Or based on belt's collision box and adjacent tiles?
   - How do we handle belt rotations (curves, turns)?

5. **Validation**:
   - Should we validate that belts can actually connect (items can flow)?
   - Or just validate placement positions?

### 3. ELECTRIC_WIRE Connection Type

**Current Status**: Methods exist (`get_pole_line()`, `get_pole_coverage_position()`, `get_pole_coverage_plan()`) but not integrated into `get_connection_positions()` with `ConnectionType.ELECTRIC_WIRE`.

**Questions**:

1. **API Design**:
   - Should `get_connection_positions()` with `ELECTRIC_WIRE` work differently?
   - Current methods are for planning pole placement, not connecting to existing poles
   - Should we have: "Given a pole, where can I place another pole to connect via wire?"

2. **Wire Distance**:
   - Each pole type has a `maximum_wire_distance` - should we use this?
   - Should we return all positions within wire distance, or just optimal positions?

3. **Pole Types**:
   - Should it support all pole types (small, medium, big, substation)?
   - Do different pole types have different wire distances?
   - Should we validate pole-to-pole compatibility?

4. **Coverage vs Connection**:
   - Current methods focus on power coverage (supply_area_distance)
   - Should ELECTRIC_WIRE focus on wire connectivity (maximum_wire_distance)?
   - Or should we have both?

5. **Return Type**:
   - Should it return `List[ConnectionPosition]` or `GhostPlan`?
   - For a line of poles, `GhostPlan` makes more sense
   - For single connection positions, `List[ConnectionPosition]` makes more sense

## General Design Questions

### Connection Position Sorting

1. **Alignment Metric**:
   - For ITEM_DROP, we use `perpendicular_offset` (distance perpendicular to flow)
   - What alignment metrics make sense for other connection types?
   - INSERTER_REACH: Distance from optimal position?
   - BELT_FLOW: Alignment with belt direction?
   - ELECTRIC_WIRE: Distance from source pole?

2. **Multiple Valid Positions**:
   - Should we always return all valid positions, or just the "best" ones?
   - Should there be a limit on the number of positions returned?
   - Should we have a "max_results" parameter?

### Entity Validation

1. **Validation Timing**:
   - Should all returned positions be pre-validated?
   - Or should validation be optional (with `validate=True` parameter)?
   - Current implementation validates all positions - is this desired?

2. **Validation Errors**:
   - What should happen if no valid positions are found?
   - Should we return empty list, or raise an exception?
   - Current implementation returns empty list - is this correct?

### Integration with GhostBuilder

1. **GhostPlan Integration**:
   - Should connection positions be returned as `GhostPlan` objects?
   - Or should `GhostPlan` be created separately by the agent?
   - Current: `get_connection_positions()` returns `List[ConnectionPosition]`
   - Should we have a `get_connection_plan()` method that returns `GhostPlan`?

2. **Label Generation**:
   - Should connection plans have labels like line plans?
   - Format: `plan:connection:{type}:{source}:{target}:{timestamp}:{hash}`?

## Testing Questions

1. **Test Coverage**:
   - What edge cases should we test for each connection type?
   - Should we test with different entity directions?
   - Should we test with obstacles in the way?

2. **Integration Tests**:
   - Should we test that entities actually connect after placement?
   - Or just that positions are valid for placement?
   - How do we verify that items actually flow, fluids connect, etc.?

## Implementation Priority

1. Which connection type should be implemented next?
2. Are there any dependencies between connection types?
3. Should we implement all connection types before integrating with GhostBuilder?
