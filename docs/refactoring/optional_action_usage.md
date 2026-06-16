# Optional Action/Operation Usage Analysis

This document catalogs all places where actions and operations are marked as Optional or have None defaults, to guide refactoring.

## Summary

**Total locations found:**
- Optional type hints: 33 locations
- None checks: 19 locations  
- None assignments/defaults: 60 locations

## 1. BaseEntity (`factory/entity/base_entity.py`)

### Optional Fields:
```python
self._entity_ops: Optional["EntityOperationsAction"] = None
self._place_ops: Optional["PlacementAction"] = None
self._walking_action: Optional["MovementAction"] = None
```

### None Checks:
- Line 189: `if self._walking_action is None:` (walk_to)
- Line 282: `if self._entity_ops is None:` (inspect)
- Line 377: `if self._place_ops is None:` (build)
- Line 396: `if self._place_ops is None:` (remove)
- Line 405: `if self._entity_ops is None:` (pickup)

---

## 2. Entity Creation (`factory/entity/create_entity.py`)

### Optional Parameters:
```python
def create_remote_view_entity(
    entity_ops: "EntityOperationsAction | None" = None,
    place_ops: "PlacementAction | None" = None,
    walking_action: "MovementAction | None" = None,
):
```

### Conditional Injection:
- Lines 266-271: Conditional assignment based on `is not None` checks

---

## 3. Entity Capabilities (Mixins)

### Optional Fields in Mixins:
- `factory/entity/capabilities/inserter.py`: `_entity_ops: Optional["EntityOperationsAction"]`
- `factory/entity/capabilities/crafter.py`: `_entity_ops: Optional["EntityOperationsAction"]` (2 locations)
- `factory/entity/implementations/container.py`: `_entity_ops: Optional["EntityOperationsAction"]`
- `factory/entity/capabilities/burner.py`: `_entity_ops: Optional["EntityOperationsAction"]`
- `factory/entity/capabilities/rotatable.py`: `_entity_ops: Optional["EntityOperationsAction"]`

### None Checks:
- `inserter.py:164`: `if self._entity_ops is None:`
- `crafter.py:96, 120, 167`: `if self._entity_ops is None:` (3 locations)
- `container.py:78, 96, 122`: `if self._entity_ops is None:` (3 locations)
- `burner.py:95, 140`: `if self._entity_ops is None:` (2 locations)

---

## 4. BaseResource (`factory/resource/base.py`)

### Optional Parameters:
```python
def __init__(
    mining_action: Optional["MiningAction"] = None,
    entity_ops: Optional["EntityOperationsAction"] = None,
):
```

### Factory Functions:
- `_create_resource_from_data()`: Both optional
- `create_resource_from_reachable()`: Both optional
- `create_resource_from_db()`: `walking_action: Optional["MovementAction"] = None`

### None Assignments:
- Line 638: `mining_action=None, entity_ops=None` (explicit None for read-only)

**Gap:** BaseResource does NOT have `_walking_action` field (only RemoteViewResource wrapper has it)

---

## 5. ResourceOrePatch (`factory/resource/base.py`)

### Optional Parameters:
```python
def __init__(
    mining_action: Optional["MiningAction"] = None,
    entity_ops: Optional["EntityOperationsAction"] = None,
):
```

---

## 6. RemoteViewResource (`factory/resource/remote_view_resource.py`)

### Optional Parameter:
```python
def __init__(
    walking_action: Optional["MovementAction"] = None,
):
```

### None Check:
- Line 92: `if self._walking_action is None:` (walk_to)

---

## 7. PlaceableItem (`factory/item/base.py`)

### Optional Parameter:
```python
def __init__(self, name: str, placement: Optional["PlacementAction"] = None):
```

### None Checks:
- Line 303: `if self._placement is None:` (place)
- Line 328: `if self._placement._entity_ops is None:` (place - checks nested)
- Line 373: `if self._placement is None:` (place_ghost)

---

## 8. ItemStack (`factory/item/base.py`)

### Optional Parameter:
```python
def __init__(
    placement: Optional["PlacementAction"] = None,
):
```

---

## 9. Item Factory Functions (`factory/item/create_item.py`)

### Optional Parameters:
- `create_item()`: `placement: Optional["PlacementAction"] = None`
- `create_item_stack()`: `placement: Optional["PlacementAction"] = None` (2 locations)

---

## 10. PlacementAction (`agent/actions/place_entity.py`)

### Optional Parameter:
```python
def __init__(
    entity_ops: Optional["EntityOperationsAction"] = None,
):
```

### None Check:
- Line 162: `if self._entity_ops is None:` (place - return_entity feature)

---

## 11. Action Response Methods

### Optional Parameters in Response Methods:
- `EntityOperationsAction.to_item_stacks()`: `placement: Optional["PlacementAction"] = None`
- `MiningAction.to_item_stacks()`: `placement: Optional["PlacementAction"] = None`
- `CraftingAction.to_item_stacks()`: `placement: Optional["PlacementAction"] = None`

---

## 12. Reachable (`agent/actions/reachable.py`)

### Optional Parameter:
```python
def __init__(
    mining_action: Optional[Any] = None,
):
```

**Note:** Creates its own `_entity_ops` and `_place_ops` instances (duplication issue)

---

## 13. QueryExecutor (`agent/snapshot/query.py`)

### Optional Parameter:
```python
def __init__(
    walking_action: Optional["MovementAction"] = None,
):
```

### None Assignments:
- Lines 240-241: `entity_ops=None, place_ops=None` (explicit None for remote entities)
- Lines 334-335: `entity_ops=None, place_ops=None` (explicit None for ghosts)

---

## 14. RemoteView (`agent/snapshot/remote_view.py`)

### Optional Parameter:
```python
def __init__(
    walking_action: Optional["MovementAction"] = None,
):
```

---

## Assignment Patterns

### Direct Assignments (26 locations):
- `create_reachable_entity()`: Direct assignment (lines 237-238)
- `create_remote_view_entity()`: Conditional assignment (lines 267-271)
- `BaseResource.__init__()`: Direct assignment (lines 45-46, 365-366)
- `ResourceOrePatch.__init__()`: Direct assignment (lines 45-46)
- `PlaceableItem.__init__()`: Direct assignment (line 238)
- `ItemStack.__init__()`: Direct assignment (line 415)
- `Reachable.__init__()`: Creates new instances (lines 60-61) ⚠️ **DUPLICATION**
- `PlacementAction.__init__()`: Direct assignment (line 119)
- `QueryExecutor.__init__()`: Direct assignment (line 63)
- `RemoteView.__init__()`: Direct assignment (line 80)
- `RemoteViewResource.__init__()`: Direct assignment (line 74)

### Usage Patterns (50+ locations):
- Direct method calls: `self._entity_ops.inspect_entity()`
- Nested access: `self._placement._entity_ops.inspect_entity()`
- Passed to factory functions: `create_reachable_entity(..., self._entity_ops, self._place_ops)`

---

## Key Patterns to Refactor

### Pattern 1: Optional Fields with None Defaults
**Location:** BaseEntity, BaseResource, PlaceableItem, ItemStack
**Issue:** Fields initialized to None, then conditionally assigned
**Fix:** Require all dependencies in `__init__`, use view/ghost booleans to control access

### Pattern 2: Conditional Injection in Factory Functions
**Location:** `create_remote_view_entity()`, `create_resource_from_db()`
**Issue:** `if action is not None:` checks before assignment
**Fix:** Always require actions, use stub implementations for read-only cases

### Pattern 3: Scattered None Checks
**Location:** 19 locations across entity capabilities and base classes
**Issue:** RuntimeError raised when action is None
**Fix:** Remove all None checks, rely on `__getattribute__` blocking based on view/ghost

### Pattern 4: Nested Optional Access
**Location:** `PlaceableItem.place()` checks `self._placement._entity_ops is None`
**Issue:** Double indirection
**Fix:** Direct access, no nested checks needed

### Pattern 5: Action Duplication
**Location:** `Reachable.__init__()` creates its own action instances
**Issue:** Duplicates Runtime's actions
**Fix:** Accept actions as constructor parameters

---

## Refactoring Strategy

**Key Insight:** Remote view is a runtime filter, not a different implementation. All entities get real actions, and `__getattribute__` blocks methods based on view/ghost booleans.

1. **Make all action dependencies required** (remove Optional)
   - BaseEntity: require `entity_ops`, `place_ops`, `walking_action`
   - BaseResource: require `mining_action`, `entity_ops`, `walking_action` (add missing walking)
   - PlaceableItem: require `placement`
   - ItemStack: require `placement`

2. **Remove all None checks** (19 locations)
   - Delete all `if self._action is None:` checks
   - Rely solely on `__getattribute__` blocking based on view/ghost status

3. **Update factory functions** to always inject all dependencies
   - `create_remote_view_entity()`: Always inject all actions (no conditional)
   - `create_resource_from_db()`: Always inject all actions
   - QueryExecutor: Pass real actions from RemoteView

4. **Fix Reachable duplication** - accept actions as parameters instead of creating new instances

5. **Update RemoteView/QueryExecutor** - pass actions through the chain
   - RemoteView gets actions from Runtime
   - QueryExecutor gets actions from RemoteView
   - Always inject all actions into entities

6. **Simplify BaseEntity.__getattribute__** - ensure it properly blocks based on view/ghost

**No stubs needed** - remote entities get real actions, but `__getattribute__` blocks most methods. Only `inspect()` and `walk_to()` work for remote entities.
