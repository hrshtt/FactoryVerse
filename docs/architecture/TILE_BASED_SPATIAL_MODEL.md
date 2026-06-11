# Tile-Based Spatial Model

> Design document for unifying spatial reasoning across FactoryVerse through discrete tile coordinates.

## Motivation

Factorio is fundamentally a **grid-based game**. Players see a grid, place entities on tiles, and reason about space in discrete units. However, our current implementation carries float positions and bounding box geometry throughout the stack, adding complexity without benefit.

By adopting a tile-based spatial model as a first-class abstraction, we:
1. **Align with how Factorio actually works** - placement is grid-based
2. **Simplify spatial queries** - integer math vs float geometry
3. **Unify Lua and Python abstractions** - same mental model on both sides
4. **Improve agent reasoning** - discrete, countable, grid-paper mental model
5. **Optimize DuckDB performance** - integer indexes vs RTREE geometry

## Terminology

Consistent naming across all layers:

| Concept | Python | DuckDB | Lua (fv_placement_hints) | Lua (fv_snapshot) |
|---------|--------|--------|--------------------------|-------------------|
| List of tiles an entity occupies | `entity.footprint_tiles` | `footprint_tiles` table | `get_entity_footprint().tiles` | `footprint_tiles` field |
| Single tile containing entity center | `entity.anchor_tile` | `tile_x`, `tile_y` columns | `anchor_tile` | `anchor_tile` field |
| Tile coordinate type | `TilePosition(x, y)` | `INTEGER` columns | `{x = int, y = int}` | `{x = int, y = int}` |
| Float coordinate type | `MapPosition(x, y)` | `DOUBLE` columns | `{x = float, y = float}` | `{x = float, y = float}` |

## Core Concepts

### Two Coordinate Systems in Factorio

| System | Type | Description | Example |
|--------|------|-------------|---------|
| **Tile Position** | Integer | Grid coordinates. Tile `(5, 5)` covers area `[5.0, 6.0) x [5.0, 6.0)`. | `{x: 5, y: 5}` |
| **Map Position** | Float | Continuous coordinates for entity centers, resource centroids. | `{x: 5.5, y: 5.5}` |

**Tile centers** are at `(n + 0.5, m + 0.5)` for integer `n, m`.

### Entity Center Snapping

Factorio snaps entity centers based on dimensions:

| Dimension | Center Snaps To | Example |
|-----------|-----------------|---------|
| **Odd** (1x1, 3x3, 5x5) | Tile center `(n+0.5, m+0.5)` | 1x1 chest at `(5.5, 5.5)` |
| **Even** (2x2, 2x3, 4x4) | Tile corner `(n, m)` | 2x2 assembler at `(10.0, 10.0)` |

### Entity Footprint as Tile List

Every grid-snapped entity occupies a deterministic set of tiles:

```
3x3 assembler at center (10.5, 10.5):

    Tiles occupied:
    ┌───┬───┬───┐
    │9,9│10,9│11,9│
    ├───┼───┼───┤
    │9,10│10,10│11,10│  ← center tile
    ├───┼───┼───┤
    │9,11│10,11│11,11│
    └───┴───┴───┘

    footprint_tiles = [
        (9,9), (10,9), (11,9),
        (9,10), (10,10), (11,10),
        (9,11), (10,11), (11,11)
    ]
```

### Footprint Calculation

Given entity center `(cx, cy)` and dimensions `(width, height)`:

```python
half_w = width / 2
half_h = height / 2

min_x = floor(cx - half_w)
max_x = floor(cx + half_w - 0.001)  # epsilon for exact boundaries
min_y = floor(cy - half_h)
max_y = floor(cy + half_h - 0.001)

tiles = [(x, y) for x in range(min_x, max_x+1) for y in range(min_y, max_y+1)]
```

This handles both odd and even dimensions correctly:
- **3x3 at (10.5, 10.5)**: `half=1.5`, `min=9`, `max=11` → 9 tiles ✓
- **2x2 at (10.0, 10.0)**: `half=1.0`, `min=9`, `max=10` → 4 tiles ✓

### Asymmetric Entities and Direction

Some entities have asymmetric footprints (e.g., 2x3). In Factorio:
- These can only rotate **180°** (not 90°) to maintain valid placement
- When facing EAST/WEST vs NORTH/SOUTH, width and height swap
- The footprint calculation accounts for this by swapping dimensions based on direction

### Exception: Resource Entities

Trees, rocks, and ore patch centroids can have **any** map position (not grid-snapped). However:
- They are **read-only** (mined, not placed)
- They can still be indexed by **containing tile**: `TilePosition.from_map_position(pos)`
- Ore patches are already tile-based in fv_snapshot (`resource_tile` table)

## Current State (Post-Implementation)

### Lua (fv_placement_hints)

Already tile-based:
```lua
-- utils/geometry.lua
function M.get_entity_footprint(entity_name, position, direction)
    -- Returns {tiles: [{x,y}...], bounding_box, tile_width, tile_height}
end

function M.snap_to_tile_center(position)
function M.snap_to_tile_corner(position)
function M.iter_area_tiles(area)
function M.get_area_tiles(area)
```

### Lua (fv_snapshot) ✅

Now includes tile information:
```lua
-- utils/serialize.lua - _serialize_base_properties()
out.anchor_tile = {
    x = math.floor(pos.x),
    y = math.floor(pos.y)
}
out.footprint_tiles = tiles  -- computed from position + dimensions + direction
```

### Python (FactoryVerse) ✅

Now has full tile-based support:
```python
# TilePosition - factory/factorio_types.py
TilePosition.from_map_position(x, y)  # Convert float to tile
TilePosition.to_map_position(center=True)  # Convert back
TilePosition.offset(direction, tiles)  # Move in direction
TilePosition.neighbors(diagonal=False)  # Adjacent tiles
TilePosition.manhattan_distance(other)
TilePosition.chebyshev_distance(other)

# BaseEntity - factory/entity/base_entity.py
entity.anchor_tile  # TilePosition of center
entity.footprint_tiles  # List[TilePosition] of all tiles
entity.footprint_tiles_set  # Set for O(1) membership
entity.occupies_tile(tile)  # Collision check
entity.collides_with(other)  # Entity-entity collision
```

### DuckDB Schema ✅

Now includes tile-based tables and columns:
```sql
-- map_entity table has anchor tile columns
CREATE TABLE map_entity (
    ...
    tile_x INTEGER,  -- anchor tile X
    tile_y INTEGER,  -- anchor tile Y
    ...
);
CREATE INDEX idx_map_entity_tile ON map_entity(tile_x, tile_y);

-- footprint_tiles table for O(1) tile lookups
CREATE TABLE footprint_tiles (
    tile_x INTEGER NOT NULL,
    tile_y INTEGER NOT NULL,
    entity_name VARCHAR NOT NULL,
    entity_position_x DOUBLE NOT NULL,
    entity_position_y DOUBLE NOT NULL,
    is_ghost BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (tile_x, tile_y)
);
CREATE INDEX idx_footprint_tiles_entity
ON footprint_tiles(entity_name, entity_position_x, entity_position_y);
```

### RemoteView Query Methods ✅

```python
# agent/remote_view.py
view.get_entity_at_tile(tile_x, tile_y)  # Entity at tile or None
view.is_tile_occupied(tile_x, tile_y)  # Fast bool check
view.get_entities_in_tile_area(min_x, min_y, max_x, max_y)  # Area query
view.get_entities_at_anchor_tile(tile_x, tile_y)  # Entities centered at tile
```

### fv_snapshot Serialization ✅

Now includes tile information:
```json
{
  "name": "assembling-machine-1",
  "position": {"x": 10.5, "y": 10.5},
  "direction": 0,
  "bounding_box": {"min_x": 9.0, "min_y": 9.0, "max_x": 12.0, "max_y": 12.0},
  "tile_width": 3,
  "tile_height": 3,
  "anchor_tile": {"x": 10, "y": 10},
  "footprint_tiles": [
    {"x": 9, "y": 9}, {"x": 10, "y": 9}, {"x": 11, "y": 9},
    {"x": 9, "y": 10}, {"x": 10, "y": 10}, {"x": 11, "y": 10},
    {"x": 9, "y": 11}, {"x": 10, "y": 11}, {"x": 11, "y": 11}
  ]
}
```

## Target State

### Python (FactoryVerse)

#### TilePosition Enhancement

```python
# factory/factorio_types.py
@dataclass(frozen=True)
class TilePosition:
    x: int
    y: int

    @classmethod
    def from_map_position(cls, pos: MapPosition) -> "TilePosition":
        """Convert map position to containing tile."""
        return cls(x=math.floor(pos.x), y=math.floor(pos.y))

    def to_map_position(self, center: bool = True) -> MapPosition:
        """Convert to map position (tile center or corner)."""
        offset = 0.5 if center else 0.0
        return MapPosition(x=self.x + offset, y=self.y + offset)

    def offset(self, direction: Direction, tiles: int = 1) -> "TilePosition":
        """Offset by N tiles in a cardinal direction."""
        vectors = {
            Direction.NORTH: (0, -1),
            Direction.EAST: (1, 0),
            Direction.SOUTH: (0, 1),
            Direction.WEST: (-1, 0),
        }
        dx, dy = vectors[direction]
        return TilePosition(x=self.x + dx * tiles, y=self.y + dy * tiles)

    def neighbors(self, diagonal: bool = False) -> List["TilePosition"]:
        """Get adjacent tiles (4 cardinal, optionally 8 with diagonals)."""
        ...
```

#### BaseEntity.footprint_tiles

```python
# factory/entity/base_entity.py
@property
def footprint_tiles(self) -> List[TilePosition]:
    """Tiles occupied by this entity.

    Computed from position and tile dimensions.
    For asymmetric entities, accounts for direction.
    """
    # Get effective dimensions (may swap for EAST/WEST asymmetric entities)
    width = self.tile_width
    height = self.tile_height
    direction = getattr(self, 'direction', None)

    if direction in (Direction.EAST, Direction.WEST) and width != height:
        width, height = height, width

    half_w = width / 2
    half_h = height / 2

    min_x = math.floor(self.position.x - half_w)
    max_x = math.floor(self.position.x + half_w - 0.001)
    min_y = math.floor(self.position.y - half_h)
    max_y = math.floor(self.position.y + half_h - 0.001)

    return [
        TilePosition(x=x, y=y)
        for x in range(min_x, max_x + 1)
        for y in range(min_y, max_y + 1)
    ]

@property
def anchor_tile(self) -> TilePosition:
    """The tile containing this entity's center."""
    return TilePosition.from_map_position(self.position)
```

#### Collision Detection

```python
def occupies_tile(self, tile: TilePosition) -> bool:
    """Check if entity occupies a specific tile."""
    return tile in self.footprint_tiles

def collides_with(self, other: "BaseEntity") -> bool:
    """Check if two entities overlap."""
    return bool(set(self.footprint_tiles) & set(other.footprint_tiles))
```

### DuckDB Schema

#### Option A: Anchor Tile Columns

```sql
ALTER TABLE map_entity ADD COLUMN tile_x INTEGER;
ALTER TABLE map_entity ADD COLUMN tile_y INTEGER;

-- Index for tile-based queries
CREATE INDEX idx_map_entity_tile ON map_entity(tile_x, tile_y);

-- Query: entities in area (tile-based)
SELECT * FROM map_entity
WHERE tile_x BETWEEN 0 AND 10
  AND tile_y BETWEEN 0 AND 10;
```

#### Option B: Footprint Tiles Table (Recommended)

```sql
CREATE TABLE footprint_tiles (
    tile_x INTEGER NOT NULL,
    tile_y INTEGER NOT NULL,
    entity_name VARCHAR NOT NULL,
    entity_position_x DOUBLE NOT NULL,
    entity_position_y DOUBLE NOT NULL,
    is_ghost BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (tile_x, tile_y)  -- Enforces one entity per tile
);

-- Index for reverse lookup (entity -> tiles)
CREATE INDEX idx_footprint_tiles_entity
ON footprint_tiles(entity_name, entity_position_x, entity_position_y);
```

**Benefits:**
- O(1) lookup: "What's at tile (5, 5)?"
- Enforces game constraint: only one entity per tile
- Efficient range queries with integer B-tree
- Consistent naming with Python `footprint_tiles` property

**Population:**
```sql
-- For each entity, insert rows for all tiles in its footprint
INSERT INTO footprint_tiles (tile_x, tile_y, entity_name, entity_position_x, entity_position_y, is_ghost)
VALUES (9, 9, 'assembling-machine-1', 10.5, 10.5, FALSE),
       (10, 9, 'assembling-machine-1', 10.5, 10.5, FALSE),
       ...
```

### fv_snapshot Serialization

Add tile information to entity JSONL:

```json
{
  "name": "assembling-machine-1",
  "position": {"x": 10.5, "y": 10.5},
  "direction": 0,
  "bounding_box": {"min_x": 9.0, "min_y": 9.0, "max_x": 12.0, "max_y": 12.0},
  "anchor_tile": {"x": 10, "y": 10},
  "tile_width": 3,
  "tile_height": 3,
  "footprint_tiles": [
    {"x": 9, "y": 9}, {"x": 10, "y": 9}, {"x": 11, "y": 9},
    {"x": 9, "y": 10}, {"x": 10, "y": 10}, {"x": 11, "y": 10},
    {"x": 9, "y": 11}, {"x": 10, "y": 11}, {"x": 11, "y": 11}
  ]
}
```

**Options for serialization:**
1. **Full `footprint_tiles` array**: No computation in loader, but more data
2. **Just `anchor_tile` + dimensions**: Less data, loader computes footprint

**Decision**: Serialize full `footprint_tiles` for consistency with the table name and to avoid recomputation. The Lua side already computes this via `geometry.get_entity_footprint()`.

### Snapshot Loader Updates

```python
# db/loader/base_loader.py
def _process_entity_data(data, ...):
    # Existing: extract position, bbox
    px, py = data["position"]["x"], data["position"]["y"]

    # New: compute anchor tile
    tile_x = math.floor(px)
    tile_y = math.floor(py)

    # New: compute footprint tiles for footprint_tiles table
    width = data.get("tile_width", 1)
    height = data.get("tile_height", 1)
    footprint_tiles = compute_footprint_tiles(px, py, width, height, direction)

    return {
        ...
        "tile_x": tile_x,
        "tile_y": tile_y,
        "footprint_tiles": footprint_tiles,
    }
```

## Query Pattern Improvements

### "What entity is at tile (5, 5)?"

**Current (geometry):**
```sql
SELECT entity_name FROM map_entity
WHERE ST_Contains(bbox, ST_Point(5.5, 5.5));
```

**Tile-based:**
```sql
SELECT entity_name FROM footprint_tiles
WHERE tile_x = 5 AND tile_y = 5;
-- O(1) with primary key
```

### "What entities are in area (0,0) to (10,10)?"

**Current (geometry):**
```sql
SELECT * FROM map_entity
WHERE ST_Intersects(bbox, ST_MakeEnvelope(0, 0, 10, 10));
```

**Tile-based:**
```sql
SELECT DISTINCT entity_name, entity_position_x, entity_position_y
FROM footprint_tiles
WHERE tile_x BETWEEN 0 AND 10
  AND tile_y BETWEEN 0 AND 10;
```

### "Is tile (5, 5) free for placement?"

**Current**: Requires geometry point-in-polygon for all nearby entities.

**Tile-based:**
```sql
SELECT COUNT(*) = 0 FROM footprint_tiles
WHERE tile_x = 5 AND tile_y = 5;
-- Single index lookup
```

## Implementation Plan

### Phase 1: Python Foundation

1. **Enhance TilePosition** in `factory/factorio_types.py`
   - Add `from_map_position()` classmethod
   - Add `to_map_position()` method
   - Add `offset(direction, tiles)` method
   - Add `neighbors()` method

2. **Add to BaseEntity** in `factory/entity/base_entity.py`
   - Add `footprint_tiles` property
   - Add `anchor_tile` property
   - Add `occupies_tile()` method
   - Add `collides_with()` method

3. **Update types.py exports**

### Phase 2: DuckDB Schema

1. **Add tile columns to map_entity**
   - `tile_x INTEGER`
   - `tile_y INTEGER`
   - Create index

2. **Create footprint_tiles table**
   - Schema as defined above
   - Indexes for both lookup directions

3. **Update schema.py** with new table definitions

### Phase 3: Snapshot Integration

1. **Update fv_snapshot Lua** (if needed)
   - Include `tile_width`, `tile_height` in entity serialization
   - Include `anchor_tile` (optional, can compute in loader)

2. **Update snapshot loader**
   - Compute `tile_x`, `tile_y` from position
   - Compute footprint tiles
   - Populate `footprint_tiles` table

### Phase 4: Query Migration ✅

1. **Added tile-based query methods to remote_view.py**:
   - `get_entity_at_tile(tile_x, tile_y)` - O(1) lookup of entity at tile
   - `is_tile_occupied(tile_x, tile_y)` - Fast collision check
   - `get_entities_in_tile_area(min_x, min_y, max_x, max_y)` - Area queries
   - `get_entities_at_anchor_tile(tile_x, tile_y)` - Entities centered at tile

2. **Query patterns documented** - see "Query Pattern Improvements" section

3. **Performance**: Integer-based queries with B-tree indexes vs RTREE geometry

### Phase 5: Agent Integration

1. **Update LLM prompts** to use tile-based language
2. **Update agent reasoning** patterns to work with tile coordinates
3. **Add tile-based helper methods** for common operations

## Testing Strategy

### Unit Tests

- `TilePosition.from_map_position()` for various positions
- `BaseEntity.footprint_tiles` for 1x1, 2x2, 3x3, asymmetric entities
- `footprint_tiles` correctness for all cardinal directions
- `collides_with()` for overlapping and non-overlapping entities

### Integration Tests

- Snapshot load → footprint_tiles table populated correctly
- DuckDB queries return same results as geometry queries
- Placement validation uses footprint_tiles correctly

### Performance Tests

- Compare tile-based vs geometry query performance
- Measure overhead of footprint_tiles table population

## Migration Notes

- **Backward compatibility**: Keep `position_x`, `position_y`, `bbox` in schema
- **Incremental adoption**: New code uses tile-based patterns; old code continues to work
- **No breaking changes**: `footprint_tiles` is additive to BaseEntity

## Open Questions

1. **Should we cache `footprint_tiles`?**
   - Currently computed on access
   - For immutable entities, could cache after first computation
   - Decision: Start without caching, add if profiling shows need

2. **Should fv_snapshot serialize full footprint_tiles?**
   - Pro: No computation in loader, consistent naming across layers
   - Con: More data (but entities are sparse compared to tiles)
   - Decision: Serialize full `footprint_tiles` array for consistency

3. **Should footprint_tiles include ghosts?**
   - Ghosts occupy tiles for placement validation
   - Could have separate `ghost_footprint_tiles` table
   - Decision: Include ghosts in same table with a `is_ghost` flag

## References

- Factorio Wiki: [Position](https://wiki.factorio.com/Types/Position)
- Factorio Wiki: [Tile](https://wiki.factorio.com/Tile)
- fv_placement_hints: `utils/geometry.lua` - existing tile-based implementation
