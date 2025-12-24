# Remote Interface ↔ DSL Type System Audit

**Audit Date**: 2025-12-25  
**Purpose**: Identify and fix gaps between Lua RemoteInterface contracts and Python DSL types  
**Status**: ✅ COMPLETE - All critical gaps fixed

---

## Summary of Changes

### New TypedDicts Added to `types.py`:

**Async Action Responses:**
- `WalkAsyncResponse` - walk_to response
- `MineAsyncResponse` - mine_resource response (includes entity_name, entity_position)
- `CraftAsyncResponse` - craft_enqueue response (includes recipe, count)

**UDP Completion Payloads:**
- `WalkCompletionPayload` - walk_to completion (success, position, elapsed_ticks)
- `MineCompletionPayload` - mine_resource completion (success, items, reason)
- `CraftCompletionPayload` - craft_enqueue completion (success, items)

**Agent/Entity Inspection:**
- `AgentActivityState` - walking/mining/crafting state
- `AgentInspectionData` - inspect() response
- `EntityEnergyData` - energy {current, capacity}
- `EntityInventoriesData` - inventories by slot type
- `HeldItemData` - inserter held item
- *(EntityInspectionData expanded with all fields)*

**Reachability Data:**
- `ReachableEntityData` - entity in get_reachable
- `ReachableResourceData` - resource in get_reachable
- `ReachableGhostData` - ghost in get_reachable
- `ReachableSnapshotData` - full get_reachable response

**Placement:**
- `PlacementCueData` - single placement cue
- `PlacementCuesResponse` - get_placement_cues response

### Methods Fixed in `agent.py`:

All methods now return typed responses instead of raw strings:

| Method | Old Return | New Return |
|--------|-----------|------------|
| `walk_to` | `Dict[str, Any]` | `WalkAsyncResponse` |
| `mine_resource` | `AsyncActionResponse` | `MineAsyncResponse` |
| `craft_enqueue` | `AsyncActionResponse` | `CraftAsyncResponse` |
| `craft_dequeue` | `str` | `ActionResult` |
| `set_entity_recipe` | `str` | `ActionResult` |
| `teleport` | `str` | `ActionResult` |
| `inspect` | `str` | `AgentInspectionData` |
| `inspect_entity` | `Dict[str, Any]` | `EntityInspectionData` |
| `get_inventory_items` | `str` | `Dict[str, int]` |
| `get_placement_cues` | `Dict[str, List[Dict]]` | `PlacementCuesResponse` |
| `get_chunks_in_view` | `str` | `Dict[str, Any]` |
| `get_recipes` | `str` | `Dict[str, Any]` |
| `get_technologies` | `str` | `Dict[str, Any]` |
| `enqueue_research` | `str` | `ActionResult` |
| `cancel_current_research` | `str` | `ActionResult` |
| `get_research_queue` | `Dict[str, Any]` | `ResearchStatus` |
| `get_reachable` | `Dict[str, Any]` | `ReachableSnapshotData` |

### RCON Contract Documentation:

All methods now have inline documentation linking to Lua schema:
```python
def walk_to(...) -> WalkAsyncResponse:
    """Walk the agent to a target position using pathfinding.

    RCON Contract: RemoteInterface.lua walk_to
    
    Returns:
        WalkAsyncResponse with {queued, action_id}
    """
```

---

## Architecture Overview

```
RemoteInterface.lua (INTERFACE_METHODS)
         │
         ▼ (RCON JSON)
    agent.py (PlayingFactory methods)
         │  ← RCON Contract comments link here
         ▼ (typed translation)
    types.py (TypedDicts) + domain objects (ItemStack, ReachableEntity, etc.)
         │
         ▼
    dsl.py (accessors for LLM agents)
```

---

## Sustainability Pattern

For future LLM maintenance:

1. **RCON Contract Comments**: Every method in `agent.py` has a docstring line:
   ```
   RCON Contract: RemoteInterface.lua method_name
   ```
   
2. **TypedDict Documentation**: Each TypedDict has:
   ```python
   """Description.
   
   RCON Contract: RemoteInterface.lua method.returns.schema
   """
   ```

3. **Validation**: Any LLM working on the DSL can verify types by:
   - Checking the RCON Contract comment
   - Looking up the Lua schema in RemoteInterface.lua
   - Ensuring TypedDict fields match

---

## Appendix: Lua Return Type Reference

Quick reference for what RCON actually returns:

```lua
-- From RemoteInterface.lua INTERFACE_METHODS

-- Async action base pattern:
async_action = {
    queued = boolean,
    action_id = string,
}

-- Common completion pattern (received via UDP):
completion = {
    success = boolean,
    ... method-specific fields ...
}

-- Common sync result pattern:
result = {
    success = boolean,
    ... method-specific fields ...
}

-- Entity reference pattern:
entity_ref = {
    success = boolean,
    entity_name = string,
    position = { x, y },
    entity_type = string,
}

-- Item reference pattern:
item_ref = {
    success = boolean,
    item_name = string,
    count = number,
}
```
