# Refactoring Plan: Remove Optional Action Dependencies

## Goal
Simplify dependency injection by always requiring all actions, using runtime filtering via `__getattribute__` to control access based on view/ghost status.

## Principle
**Remote view is a runtime filter, not a different implementation.** All entities get real actions; `__getattribute__` blocks methods based on view/ghost booleans.

## Current State
- 33 Optional type hints
- 19 None checks scattered throughout
- Conditional injection in factory functions
- Action duplication in Reachable

## Target State
- All action dependencies required (no Optional)
- Zero None checks
- Always inject all actions
- Runtime filtering via `__getattribute__` handles access control

---

## Step-by-Step Refactoring

### Phase 1: BaseEntity (Core Entity Class)

**File:** `factory/entity/base_entity.py`

**Changes:**
1. Remove Optional from field declarations:
   ```python
   # Before:
   self._entity_ops: Optional["EntityOperationsAction"] = None
   self._place_ops: Optional["PlacementAction"] = None
   self._walking_action: Optional["MovementAction"] = None
   
   # After:
   self._entity_ops: "EntityOperationsAction"
   self._place_ops: "PlacementAction"
   self._walking_action: "MovementAction"
   ```

2. Update `__init__` to require all dependencies:
   ```python
   def __init__(
       self,
       name: str,
       position: MapPosition,
       entity_ops: "EntityOperationsAction",
       place_ops: "PlacementAction",
       walking_action: "MovementAction",
       is_ghost: bool = False,
       ghost_name: Optional[str] = None,
       view: EntityView = EntityView.REMOTE,
       **kwargs,
   ):
   ```

3. Remove all None checks (5 locations):
   - Line 189: `walk_to()` - remove check
   - Line 282: `inspect()` - remove check
   - Line 377: `build()` - remove check
   - Line 396: `remove()` - remove check
   - Line 405: `pickup()` - remove check

4. Simplify methods to directly use actions (no checks needed)

---

### Phase 2: Entity Factory Functions

**File:** `factory/entity/create_entity.py`

**Changes:**
1. Update `_create_base_entity()` to accept and pass all actions:
   ```python
   def _create_base_entity(
       entity_data: Dict[str, Any],
       entity_ops: "EntityOperationsAction",
       place_ops: "PlacementAction",
       walking_action: "MovementAction",
       is_ghost: bool = False,
       view: EntityView = EntityView.REMOTE,
   ) -> "BaseEntity":
   ```

2. Update `create_reachable_entity()` - already requires actions, just pass through:
   ```python
   def create_reachable_entity(
       entity_data: Dict[str, Any],
       entity_ops: "EntityOperationsAction",
       place_ops: "PlacementAction",
       walking_action: "MovementAction",
       is_ghost: bool = False,
   ) -> "BaseEntity":
       return _create_base_entity(
           entity_data,
           entity_ops=entity_ops,
           place_ops=place_ops,
           walking_action=walking_action,
           is_ghost=is_ghost,
           view=EntityView.REACHABLE,
       )
   ```

3. Update `create_remote_view_entity()` - remove conditional injection:
   ```python
   def create_remote_view_entity(
       entity_data: Dict[str, Any],
       entity_ops: "EntityOperationsAction",
       place_ops: "PlacementAction",
       walking_action: "MovementAction",
       is_ghost: bool = False,
   ) -> "BaseEntity":
       return _create_base_entity(
           entity_data,
           entity_ops=entity_ops,
           place_ops=place_ops,
           walking_action=walking_action,
           is_ghost=is_ghost,
           view=EntityView.REMOTE,
       )
   ```

---

### Phase 3: Entity Capabilities (Mixins)

**Files:**
- `factory/entity/capabilities/inserter.py`
- `factory/entity/capabilities/crafter.py`
- `factory/entity/implementations/container.py`
- `factory/entity/capabilities/burner.py`
- `factory/entity/capabilities/rotatable.py`

**Changes:**
1. Remove Optional from `_entity_ops` field declarations (5 locations)
2. Remove all None checks (9 locations total):
   - inserter.py: 1 check
   - crafter.py: 3 checks
   - container.py: 3 checks
   - burner.py: 2 checks

3. Methods can directly use `self._entity_ops` without checks

---

### Phase 4: BaseResource

**File:** `factory/resource/base.py`

**Changes:**
1. Add missing `_walking_action` field:
   ```python
   def __init__(
       self,
       name: str,
       position: MapPosition,
       resource_type: str,
       data: Dict[str, Any],
       mining_action: "MiningAction",
       entity_ops: "EntityOperationsAction",
       walking_action: "MovementAction",
   ):
   ```

2. Add `walk_to()` method (like BaseEntity):
   ```python
   async def walk_to(self, timeout: Optional[int] = None) -> "MapPosition":
       return await self._walking_action.walk_to_entity(
           entity_name=self.name,
           entity_position=self.position,
           timeout=timeout,
       )
   ```

3. Remove Optional from all factory functions:
   - `_create_resource_from_data()`
   - `create_resource_from_reachable()`
   - `create_resource_from_db()` (add walking_action parameter)

4. Update ResourceOrePatch to require all actions

---

### Phase 5: RemoteViewResource

**File:** `factory/resource/remote_view_resource.py`

**Changes:**
1. Remove Optional from `walking_action` parameter
2. Remove None check in `walk_to()` method
3. Always require `walking_action` in `__init__`

---

### Phase 6: PlaceableItem and ItemStack

**File:** `factory/item/base.py`

**Changes:**
1. Remove Optional from `placement` parameter in `PlaceableItem.__init__()`
2. Remove Optional from `placement` parameter in `ItemStack.__init__()`
3. Remove all None checks (3 locations):
   - Line 303: `place()` - remove check
   - Line 328: `place()` - remove nested check for `_placement._entity_ops`
   - Line 373: `place_ghost()` - remove check

4. Simplify `place()` method - no nested checks needed

**File:** `factory/item/create_item.py`

**Changes:**
1. Remove Optional from all `placement` parameters (3 locations)
2. Always require placement in factory functions

---

### Phase 7: PlacementAction

**File:** `agent/actions/place_entity.py`

**Changes:**
1. Remove Optional from `entity_ops` parameter
2. Remove None check in `place()` method (line 162)
3. Always require `entity_ops` in `__init__`

**Note:** This means PlacementAction always needs entity_ops, which is fine since it's used for `return_entity=True` feature.

---

### Phase 8: Reachable (Fix Duplication)

**File:** `agent/actions/reachable.py`

**Changes:**
1. Accept actions as constructor parameters instead of creating new instances:
   ```python
   def __init__(
       self,
       rcon_handler: "RconHandler",
       entity_ops: "EntityOperationsAction",
       place_ops: "PlacementAction",
       walking_action: "MovementAction",
       mining_action: Optional["MiningAction"] = None,  # Still optional for resources
   ):
       self._rcon = rcon_handler
       self._entity_ops = entity_ops
       self._place_ops = place_ops
       self._walking_action = walking_action
       self._mining_action = mining_action
   ```

2. Remove lines 60-61 (creating new instances)

3. Update Runtime to pass actions to Reachable:
   ```python
   self._reachable = Reachable(
       self._rcon,
       self._entity_ops,
       self._placement,
       self._walking,
       self._mining,
   )
   ```

---

### Phase 9: QueryExecutor and RemoteView

**File:** `agent/snapshot/query.py`

**Changes:**
1. Accept all actions as constructor parameters:
   ```python
   def __init__(
       self,
       connection: duckdb.DuckDBPyConnection,
       entity_ops: "EntityOperationsAction",
       place_ops: "PlacementAction",
       walking_action: "MovementAction",
   ):
   ```

2. Update `_construct_entity()` and `_construct_ghost()` to always pass all actions (remove None assignments)

**File:** `agent/snapshot/remote_view.py`

**Changes:**
1. Accept all actions as constructor parameters:
   ```python
   def __init__(
       self,
       snapshot_dir: Path,
       entity_ops: "EntityOperationsAction",
       place_ops: "PlacementAction",
       walking_action: "MovementAction",
       db_path: Optional[Path] = None,
       udp_dispatcher: Optional["UDPDispatcher"] = None,
   ):
   ```

2. Pass actions to QueryExecutor in `load()` method

3. Update Runtime to pass actions to RemoteView:
   ```python
   self._remote_view = RemoteView(
       snapshot_dir=snapshot_dir,
       entity_ops=self._entity_ops,
       place_ops=self._placement,
       walking_action=self._walking,
       db_path=config.db_path,
       udp_dispatcher=get_udp_dispatcher(),
   )
   ```

---

### Phase 10: Action Response Methods

**Files:**
- `agent/actions/entity_operations.py`
- `agent/actions/mining.py`
- `agent/actions/crafting.py`

**Changes:**
1. Keep `placement` as Optional in `to_item_stacks()` methods - these are convenience methods, not core dependencies

---

## Testing Strategy

After each phase:
1. Run existing tests to ensure no regressions
2. Verify that remote entities can still `inspect()` and `walk_to()`
3. Verify that remote entities are blocked from mutation methods
4. Verify that ghost entities can `build()` and `remove()`
5. Verify that ghost entities are blocked from other mutation methods

---

## Expected Benefits

1. **Reduced code:** Remove 19 None checks + conditional injection logic
2. **Clearer contracts:** All dependencies explicit in signatures
3. **Better type safety:** No Optional types to handle
4. **Simpler mental model:** Actions always present, filtering via `__getattribute__`
5. **Easier testing:** Can always mock actions, no None cases to handle

---

## Migration Notes

- All factory functions must be updated to always provide actions
- Runtime must pass actions through the chain: Runtime → Reachable/RemoteView → Entities
- No breaking changes to public API (methods still work the same, just no None checks internally)
