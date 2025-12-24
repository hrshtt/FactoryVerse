# Verification Loop Section - Draft

## The Verification Loop: Treating Actions as Hypotheses

In FactoryVerse, **assume your internal state is stale**. The database is the source of truth, not your memory. Every action is a hypothesis about the world that must be verified.

### The Scientific Method Pattern

```
1. Hypothesize: "I intend to place a drill at (10, 10)"
2. Action: Execute the DSL code
3. Verify: Query the database - "Is there a drill at (10, 10)?"
4. Analyze: If no → diagnose the divergence
5. Adapt: Adjust strategy based on what you learned
```

This isn't "error handling" - it's **empirical confirmation**. Failures are sensor readings that reveal the true state of the world.

---

### Three Failure Layers

**Layer 1: Execution Failure (The Exception)**
- API throws error: `CollisionError`, `TimeoutError`, etc.
- **Agent mindset**: "My action failed, therefore I learned something new (there's an obstacle)"
- **Example**: `place()` raises collision → I now know that position is occupied without querying

**Layer 2: State Divergence (The Silent Failure)**  
- Code executes without error, but world state doesn't match expectation
- **Agent mindset**: "The code ran, but did the world actually change?"
- **Example**: Called `craft('gear')` but inventory count didn't increase → likely missing ingredients
- **Most dangerous** because no obvious signal

**Layer 3: Strategic Deadlock (The Loop)**
- Agent retries same failed strategy repeatedly without progress
- **Agent mindset**: "My approach isn't working, I need a different strategy"
- **Example**: Trying to walk through obstacle 5 times → query for alternate path or remove obstacle

---

### Common Failure Patterns & Recovery

#### The Silent Fail (Effect Missing)
**Symptom**: Action completes successfully but expected state change doesn't occur

**Examples**:
- `craft('iron-gear-wheel')` returns but inventory unchanged
- `place(drill_item, position)` returns but database shows no entity
- `add_fuel(coal_stacks)` returns but entity still has no fuel

**Diagnosis**:
```python
# After crafting
iron_gears_before = inventory.get_total('iron-gear-wheel')
await crafting.craft('iron-gear-wheel', count=5)
iron_gears_after = inventory.get_total('iron-gear-wheel')

if iron_gears_after == iron_gears_before:
    # Silent failure! Likely missing ingredients
    iron_plates = inventory.get_total('iron-plate')
    print(f"Crafting failed - only have {iron_plates} iron plates, need {5*2}")
```

**Recovery**: Query preconditions (inventory, entity state) → gather missing resources → retry

#### The Physics Fail (Collision/Unreachable)
**Symptom**: Action rejected due to physical constraints

**Examples**:
- `place()` returns collision error
- `walking.to()` times out
- Entity placement out of reach

**Diagnosis**:
```python
# After placement failure
result = drill_item.place(MapPosition(x=10, y=10))

if not result.success:
    # Query what's blocking
    blocking = con.execute("""
        SELECT entity_name, position.x, position.y
        FROM map_entity
        WHERE ST_Intersects(
            bbox,
            ST_Buffer(ST_Point(?, ?), 2)
        )
    """, [10, 10]).fetchall()
    
    print(f"Collision with: {blocking}")
    # Adapt: Remove obstacle, try different position, or walk closer
```

**Recovery**: Query spatial context → remove obstacle OR choose alternate position

#### The Stale Reference Fail
**Symptom**: "Entity doesn't exist" error when trying to interact with a Python reference

**What it means**: You're holding a reference too long between query and use

**Examples**:
- Queried `drill = reachable.get_entity("burner-mining-drill")` 
- Did 20 turns of other work
- Tried `drill.add_fuel(coal)` → "entity doesn't exist" error

**Why it happens**:
- **Single agent**: You held the reference across too many operations
- **Multi-agent/multiplayer**: Another agent/player modified state between your query and action
- Python references are **snapshots**, not live connections to game entities

**The rule**: **Query fresh when you need it, use immediately**

```python
# ❌ BAD: Holding reference across many operations
drill = reachable.get_entity("burner-mining-drill")  # Turn 1
# ... lots of other work ...
drill.add_fuel(coal)  # Turn 20 - RISK: reference may be stale

# ✅ GOOD: Fresh query right before use
# ... lots of other work ...
drill = reachable.get_entity("burner-mining-drill")  # Fresh query
if drill:
    drill.add_fuel(coal)  # Immediate use
else:
    print("Drill no longer exists - replanning needed")
```

**Recovery**: 
- Don't just catch and retry the same pattern
- Refactor to query closer to usage
- Use DuckDB for long-term planning, `reachable` for immediate action
- In multi-agent scenarios, expect more volatility - tighten query-action loops

**Important**: Frequent stale reference errors mean **you're doing something wrong** (holding references too long), not that the system is broken.

---

### The Verification Checklist

Focus verification on **state changes you initiated**, not on reference validity:

**After placement** (verify the action succeeded):
```python
result = drill_item.place(pos)

# Check if placement succeeded
if result.success:
    # Optionally verify in database for critical placements
    placed = con.execute("""
        SELECT entity_key FROM map_entity
        WHERE entity_name = 'burner-mining-drill'
        AND position.x = ? AND position.y = ?
    """, [pos.x, pos.y]).fetchone()
    
    if not placed:
        # Silent failure - investigate why
else:
    # Placement failed - handle the specific error
```

**After walking**:
```python
await walking.to(target_pos)

# Verify you arrived
current_pos = reachable.get_current_position()
distance = current_pos.distance(target_pos)

if distance > 2:  # Not close enough
    # Walking failed or interrupted
    print(f"Failed to reach destination, {distance:.1f} tiles away")
```

**After crafting/mining**:
```python
iron_before = inventory.get_total('iron-ore')
await resource.mine(max_count=25)
iron_after = inventory.get_total('iron-ore')

items_mined = iron_after - iron_before
if items_mined == 0:
    # Resource depleted or not reachable
    print("Mining failed - resource depleted or unreachable")
```

---

### Information Sources: Three Levels of Freshness

**DuckDB (Synchronized Authority)**:
- Source of truth for world state
- Use for planning, analysis, spatial queries
- Data synchronized continuously via background service
- Best for: "Where should I build?" "What resources are available?"

**Reachable Queries (Fresh Snapshots)**:
- Current state of entities/resources in reach
- Use when you need to act immediately
- Query right before action, use immediately
- Best for: "What can I interact with right now?"

**Python References (Expiring Snapshots)**:
- References to entities at query time
- Can become stale if held too long
- Use immediately after fetching, don't hold across operations
- Best for: Short-lived interactions within same turn

**The pattern**:
```python
# Planning: Use DuckDB
best_iron_patch = con.execute("""
    SELECT ST_X(centroid) as x, ST_Y(centroid) as y
    FROM resource_patch WHERE resource_name = 'iron-ore'
    ORDER BY total_amount DESC LIMIT 1
""").fetchone()

# Walk to location
await walking.to(MapPosition(x=best_iron_patch[0], y=best_iron_patch[1]))

# Action: Query fresh, use immediately
iron_resources = reachable.get_resources("iron-ore")
if iron_resources:
    await iron_resources[0].mine(max_count=25)
```

---

### When Verification Reveals Failure

**Don't retry blindly**. Diagnose and adapt:

1. **Query to understand WHY** - What's the actual state vs expected state?
2. **Update mental model** - Your assumption was wrong, what's really there?
3. **Generate alternatives** - Different position? Different strategy? Different resource?
4. **Try new approach** - Don't repeat the same failed action

**Example**:
```python
# Placement failed 3 times at planned positions
# ❌ BAD: Keep trying same positions
# ✅ GOOD: Query and adapt

# Find WHY it's failing
obstacles = query_obstacles_in_area(planned_area)

if obstacles:
    # Strategy A: Clear the obstacles
    for obstacle in obstacles:
        await clear_obstacle(obstacle)
    
    # Strategy B: Find different area
    alternative_positions = query_clear_area_near(planned_area)
```

---

### Summary: Be a Scientist, Not a Programmer

- **Hypothesis**: State your intent before acting
- **Experiment**: Execute the action
- **Observation**: Query to verify the outcome
- **Analysis**: Understand divergence between intent and reality
- **Adaptation**: Adjust strategy based on what you learned

Failures aren't bugs - they're data. Use them to build accurate mental models of the game state.
