# View Method Consolidation Design

> Goal: Reduce system prompt tokens by ~1,500 by removing redundant method documentation.

## Current State (Verbose)

### ReachableView
```python
get_entity(entity_name, position, options) -> Optional[BaseEntity]  # singular
get_entities(entity_name, options) -> List[BaseEntity]               # plural
get_ghosts(entity_name) -> List[BaseEntity]                          # bespoke
get_resource(resource_name, position) -> Optional[BaseResource]      # singular
get_resources(resource_name, resource_type) -> List[BaseResource]    # plural
```

### RemoteView
```python
get_entity(sql) -> Optional[BaseEntity]      # singular (LIMIT 1)
get_entities(sql) -> List[BaseEntity]        # plural
get_ghosts(sql) -> List[BaseEntity]          # bespoke
get_resources(sql) -> List[BaseResource]     # resources
query(sql) -> List[Dict]                     # raw SQL
# + tile methods (keep as-is)
```

## Target State (Consolidated)

### ReachableView
```python
get_entity(
    entity_name: Optional[str] = None,
    position: Optional[MapPosition] = None,
    options: Optional[Dict] = None,  # include_ghosts, ghosts_only, recipe, status, etc.
    limit: Optional[int] = None,     # NEW: limit=1 for single result
) -> List[BaseEntity]

get_resources(
    resource_name: Optional[str] = None,
    resource_type: Optional[str] = None,  # "ore", "entity", "tree", "rock"
    position: Optional[MapPosition] = None,
    limit: Optional[int] = None,
) -> List[BaseResource]
```

### RemoteView
```python
get_entity(sql) -> List[BaseEntity]      # Always returns list (no LIMIT auto-add)
get_resources(sql) -> List[BaseResource] # Resources from SQL
query(sql) -> List[Dict]                 # Raw SQL
# + tile methods (keep as-is)
```

## Key Design Decisions

### 1. Remove Singular/Plural Distinction
- **Before**: `get_entity()` vs `get_entities()`
- **After**: `get_entity()` always returns `List[BaseEntity]`
- **Rationale**: Simpler API surface. Agent uses `limit=1` or `[0]` when needed.

### 2. Remove `get_ghosts()` Bespoke Method
- **ReachableView**: Use `get_entity(options={'ghosts_only': True})`
- **RemoteView**: Use SQL against `ghost` table or `WHERE is_ghost = true`
- **Rationale**: Ghosts are just entities with a filter - don't need special method.

### 3. Keep `query()` on RemoteView
- Raw SQL is essential for aggregations, counts, custom joins
- Not duplicating this with `get_entity`

### 4. Keep Tile Methods on RemoteView
- `is_tile_occupied`, `get_entity_at_tile`, `get_entities_in_tile_area`, `get_entities_at_anchor_tile`
- These are specialized spatial queries, not redundant

## Token Impact (Measured)

### View Methods
- Before: ~3,182 tokens (RemoteView: 1,756 + ReachableView: 1,426)
- After: 279 tokens
- **View savings: 2,903 tokens (91% reduction)**

### Combined with Schema Reference
| Component | Before | After | Savings |
|-----------|--------|-------|---------|
| API Reference (DSL) | 15,044 | 11,428 | 3,616 |
| Schema Reference (DB) | 4,257 | 3,344 | 913 |
| **Total** | **19,301** | **14,772** | **4,529 (23.5%)** |

### Methods Removed
- `get_entities()` → consolidated into `get_entity()`
- `get_ghosts()` → use `get_entity(options={'ghosts_only': True})` or SQL
- `get_resource()` → consolidated into `get_resources()`

## Migration Notes

### Breaking Changes
1. `get_entity()` return type changes from `Optional[BaseEntity]` to `List[BaseEntity]`
2. `get_entities()` removed - use `get_entity()`
3. `get_ghosts()` removed - use `get_entity(options={'ghosts_only': True})` or SQL

### Code Update Pattern
```python
# Before
entity = reachable_view.get_entity("stone-furnace")
if entity:
    ...

# After
entities = reachable_view.get_entity("stone-furnace", limit=1)
if entities:
    entity = entities[0]
    ...

# Or more idiomatically:
entities = reachable_view.get_entity("stone-furnace")
for entity in entities:
    ...  # Works for 0, 1, or many
```

## Implementation Checklist

1. [x] Update `ReachableView`:
   - [x] Merge `get_entity` + `get_entities` → `get_entity` returning List
   - [x] Add `limit` parameter
   - [x] Remove `get_ghosts()` method
   - [x] Merge `get_resource` + `get_resources` → `get_resources` returning List
   - [x] Add `position` and `limit` parameters to `get_resources`

2. [x] Update `RemoteView`:
   - [x] Remove `get_entity` singular method (use `get_entities` SQL with LIMIT 1)
   - [x] Rename `get_entities` → `get_entity` (returns List)
   - [x] Remove `get_ghosts()` method

3. [x] Update documentation:
   - [x] `src/FactoryVerse/utils/docs/reference/views.py` - consolidated methods
   - [x] `src/FactoryVerse/infra/llm/prompts/schema_reference.py` - updated examples

4. [ ] Update tests that use the old API (remaining)

5. [x] Measure token savings: **4,529 tokens (23.5%)**
