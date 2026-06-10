# Entity Walking Integration & Dependency Injection Refactor

**Date**: 2026-01-12
**Status**: Implemented

## 1. Overview

This effort integrated entity-aware navigation ("Walk to this Assembler") into the `RemoteViewResource` and `BaseEntity` systems. It replaced position-based approximations with a robust, robust pathfinding system that understands entity bounding boxes and interaction ranges.

To support this, a full Dependency Injection (DI) pipeline was established to pass agent actions (`MovementAction`, `EntityOperationsAction`, etc.) from the `AgentRuntime` down to the read-only entities created by `RemoteView` queries.

---

## 2. Functional Changes

### A. Smart Entity Walking
*   **Behavior**: Agents can now be told to "walk to Iron Ore Patch". The system calculates valid standing spots *near* the target, filtering out blocked tiles (pipes, water).
*   **Fallback**: If the primary approach path is blocked, the agent automatically retries with alternative candidate tiles without needing Python-side intervention.
*   **Diagnostics**: Detailed failure reasons (`ENTITY_NOT_FOUND`, `NO_STANDABLE_TILES`, `UNREACHABLE`) are reported back to the agent.

### B. "Actionable" Remote Views
*   **RemoteViewResource**: Resources queried from `remote_view` (e.g., `remote_view.get_resources()`) now have a functional `await resource.walk_to()` method.
*   **Remote Entities**: Entities queried from `remote_view` (e.g., `remote_view.get_entities()`) also support `walk_to()`.
*   **Reachable vs. Remote**:
    *   `RemoteView` objects (read-only snapshots) **have** `walk_to`.
    *   `Reachable` objects (interactable, in-range) **do not** expose `walk_to` (calling it raises a runtime error or is structurally blocking), encouraging the use of interaction methods (`mine`, `open`) instead.

---

## 3. Implementation Details

### A. Lua Layer (`walking.lua`)
*   **`walk_to(goal, ...)`**: Updated to accept an optional `entity_ref` in options.
*   **`compute_approach_candidates`**: New algorithm to finding valid valid 1x1 standing tiles around an entity's perimeter, respecting the agent's reach distance.
*   **State Machine**: Added logic to iterate through candidate tiles if the pathfinder returns `result.status == generic_path_finder_status.no_path`.
*   **Failure Reporting**: UDP failure packets now include a `failure_type` string.

### B. Lua Interface (`RemoteInterface.lua`)
*   **Schema Update**: Updated `walk_to` documentation and parameter specification to include the `entity_ref` option.
*   **Return Values**: Added `failure_type` and `candidates_tried` to the completion schema.

### C. Python Action Layer (`walking.py`)
*   **Properties**: mapped `WalkingFailed` payload to specific Python exceptions:
    *   `WalkingUnreachableError`
    *   `WalkingEntityNotFoundError`
    *   `WalkingNoStandableTilesError`
*   **Methods**: Added `walk_to_entity(name, position)` helper that constructs the `entity_ref` payload for Lua.

### D. Entity System (`base_entity.py`, `create_entity.py`)
*   **`BaseEntity`**:
    *   Added injected field: `_walking_action: "MovementAction"`.
    *   Added method: `async walk_to()`. Delegates to `_walking_action.walk_to_entity`.
*   **Factory Functions**:
    *   `create_remote_view_entity`: Updated to accept `walking_action`.
    *   `create_reachable_entity`: Left as-is (walking not injected), ensuring reachable entities don't encourage redundant walking.

### E. Resource System (`resource/base.py`, `remote_view_resource.py`)
*   **`RemoteViewResource`**:
    *   Added `walk_to()` method.
    *   Accepts `walking_action` in constructor.
*   **`create_resource_from_db`**: Updated to inject `walking_action` into the generic resource wrapper.

### F. Dependency Injection Pipeline (`runtime.py`, `remote_view.py`, `query.py`)
This was the core architectural change to enable the above features. Dependencies are now passed down the chain:

1.  **`AgentRuntime`**: Instantiates actions (`walking`, `mining`, `entity_ops`, `placement`).
    *   *Passes all actions to `RemoteView` constructor.*
2.  **`RemoteView`**: Stores actions.
    *   *Passes actions to `QueryExecutor`.*
3.  **`QueryExecutor`**: Executes SQL.
    *   *Passes actions to factory functions (`create_remote_view_entity`, `create_resource_from_db`) when converting rows to objects.*
4.  **Factory Functions**:
    *   *Inject actions into `BaseEntity` / `RemoteViewResource` instances.*

## 4. Overall Flow

```mermaid
graph TD
    User["Agent/User"] -->|1. remote_view.get_entities()| Runtime[AgentRuntime]
    Runtime --> RemoteView
    RemoteView --> QueryExecutor
    QueryExecutor -->|SQL| DuckDB
    DuckDB -->|Rows| QueryExecutor
    QueryExecutor -->|Inject Actions| Factory[create_remote_view_entity]
    Factory -->|Returns| Entity[RemoteEntity instance]
    
    User -->|2. await entity.walk_to()| Entity
    Entity -->|3. Delegates| MovementAction
    MovementAction -->|4. RCON| Lua[Factorio Mod]
    Lua -->|5. Pathfinding| GameState
    Lua -->|6. UDP Success/Fail| MovementAction
    MovementAction -->|7. Return/Raise| User
```
