# Map View System

Non-blocking parallel observation interface for Factorio game state.

## Usage

### Server Mode (Default)

```python
import asyncio
from FactoryVerse.observations import MapView

# Initialize map view for server (auto-detects .fv-output/output_0)
map_view = MapView(mode="server", instance_id=0)

# Or specify work directory
from pathlib import Path
map_view = MapView(mode="server", instance_id=0, work_dir=Path("/path/to/project"))

# Start the map view (loads initial snapshot and begins listening to UDP)
await map_view.start()
await map_view.load_initial_snapshot()
await map_view.wait_for_initial_load()
```

### Client Mode

```python
import asyncio
from FactoryVerse.observations import MapView

# Initialize map view for client (auto-detects local Factorio directory)
map_view = MapView(mode="client")

# Start the map view
await map_view.start()
await map_view.load_initial_snapshot()
await map_view.wait_for_initial_load()
```

### Manual Override

```python
from pathlib import Path
from FactoryVerse.observations import MapView

# Override snapshot directory manually
map_view = MapView(snapshot_dir=Path("/custom/path/to/snapshots"))

# Query entities in an area
entities = map_view.get_entities_in_area(
    min_x=0, min_y=0, max_x=100, max_y=100,
    entity_type="assembling-machine"
)

# Query entities near a position
nearby = map_view.get_entities_near(x=50, y=50, radius=10)

# Query resources
resources = map_view.get_resources_in_area(
    min_x=0, min_y=0, max_x=100, max_y=100,
    resource_kind="iron-ore"
)

# Get specific entity
entity = map_view.get_entity(unit_number=12345)

# Advanced SQL query
results = map_view.query("""
    SELECT * FROM entities
    WHERE type = 'inserter'
    AND position_x BETWEEN 0 AND 100
    ORDER BY position_x, position_y
""")

# Cleanup
await map_view.stop()
```

## Integration with RCON Helper

**Note**: Both `MapView` and `RconHelper.AsyncActionListener` listen on UDP port 34202. They filter events by `event_type`:
- `MapView` processes: `file_created`, `file_updated`, `file_deleted`
- `AsyncActionListener` processes: action completion events (with `action_id`)

If you're using both, they can coexist on the same port since they filter different event types.

## File Structure

The snapshot directory structure is:
```
factoryverse/snapshots/
├── {chunk_x}/
│   └── {chunk_y}/
│       ├── entities/
│       │   └── {pos_x}_{pos_y}_{entity_name}.json
│       ├── belts/
│       ├── pipes/
│       ├── poles/
│       └── resources/
│           ├── resources.jsonl
│           └── water.jsonl
```

## Performance

- Initial load: Loads all existing snapshot files (may take time for large maps)
- Incremental updates: Real-time via UDP notifications
- Query performance: Fast with DuckDB spatial indexes
- Memory: In-memory database (per notebook instance)

