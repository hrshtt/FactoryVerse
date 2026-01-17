# Modular Boilerplate for FactoryVerse

This module provides **scope-based, composable loading** of FactoryVerse infrastructure. Instead of loading everything at once, you can choose the exact scope you need:

## Scopes

| Scope | Int | Description | Components |
|-------|-----|-------------|------------|
| `RCON` | 0 | Raw RCON connection | `config`, `instance`, `rcon` |
| `SNAPSHOT` | 1 | + Data persistence | `database`, `snapshot_loader`, `db_path` |
| `AGENT` | 2 | + Embodied agent | `agent_id`, `udp_port`, `entity_list` |
| `RUNTIME` | 3 | + Full affordances | `runtime`, `walking`, `crafting`, etc. |

**Scopes are cumulative** - each scope includes all lower scopes.

## Quick Start

### Python API

```python
from FactoryVerse.infra.llm.boilerplate import load, Scope

# Load just RCON for testing Lua commands
ctx = load(scope=Scope.RCON)
result = ctx['rcon'].send_command('/c print("hello")')

# Load snapshot scope for testing DuckDB queries  
ctx = load(scope=Scope.SNAPSHOT)
result = ctx['database'].connection.execute("SELECT * FROM map_entity LIMIT 10")

# Load full runtime (default)
ctx = load()  # scope=Scope.RUNTIME
await ctx.start()
await ctx['runtime'].walking.walk_to(MapPosition(10, 10))
```

### Session Management (for MCP/Development)

```python
from FactoryVerse.infra.llm.boilerplate import create_session, get_session, destroy_session

# Create a session
session = create_session(
    session_id='dev_1',
    scope=Scope.AGENT,
    instance='server_0',
    agent_id='agent_1',
)
await session.start()

# Get session later
session = get_session('dev_1')

# Reload after code changes
await session.reload(reload_lua=True)

# Cleanup
await destroy_session('dev_1')
```

## MCP Tools

The MCP server exposes these tools for session management:

| Tool | Description |
|------|-------------|
| `factoryverse_create_session` | Create session at specified scope |
| `factoryverse_execute_in_session` | Execute code in session context |
| `factoryverse_reload_session` | Reload Python modules (+ optional Lua) |
| `factoryverse_destroy_session` | Destroy session and cleanup |
| `factoryverse_list_sessions` | List active sessions |

### Example MCP Usage

```json
{
  "tool": "factoryverse_create_session",
  "arguments": {
    "session_id": "test_snapshot",
    "scope": 1,
    "instance": "server_0"
  }
}
```

## Module Structure

```
boilerplate/
├── __init__.py         # Main API: Scope, load(), create_session()
├── rcon.py             # Scope.RCON loader
├── snapshot.py         # Scope.SNAPSHOT loader
├── agent.py            # Scope.AGENT loader
├── runtime.py          # Scope.RUNTIME loader
├── test_ground.py      # TestGround helper utilities
├── mcp.py              # MCP-specific async functions
└── README.md           # This file
```

## Design Rationale

### Why Scopes?

1. **Faster iteration** - Load only what you need for testing
2. **Isolation** - Test one layer without others
3. **Resource efficiency** - Don't create agents/UDP listeners unnecessarily
4. **MCP flexibility** - Create multiple sessions at different scopes

### Why Python files (not strings)?

1. **IDE support** - Linting, navigation, autocomplete
2. **Version control** - Track changes, diff, blame
3. **Import validation** - Python catches import errors early
4. **Documentation** - Docstrings render in IDE

### Why Session Management?

For MCP-based development, we need:
- Multiple concurrent sessions for A/B testing
- Hot-reload without restarting MCP server
- Programmatic lifecycle control
- Resource cleanup on session end

## Legacy Compatibility

The original `boilerplate.py` file is unchanged and still works for Jupyter notebooks. The new module provides an alternative API for programmatic control.

```python
# Legacy (still works)
# Loads boilerplate.py as a string into Jupyter kernel

# New (modular)
from FactoryVerse.infra.llm.boilerplate import load, Scope
ctx = load(scope=Scope.RUNTIME)
```

## Testing

Use scopes in tests for focused testing:

```python
@pytest.fixture
async def rcon_ctx():
    """Just RCON for Lua tests."""
    ctx = load(scope=Scope.RCON)
    yield ctx
    # No cleanup needed - just RCON

@pytest.fixture
async def snapshot_ctx():
    """Snapshot scope for DuckDB tests."""
    ctx = load(scope=Scope.SNAPSHOT)
    yield ctx
    ctx['database'].close()
```
