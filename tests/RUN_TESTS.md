# Running Tests Against Different Factorio Instances

The test suite can run against either Docker servers or your local Factorio client.

## Quick Start

### Against Docker Server (default)
```bash
# Uses auto-detection (prefers server_0 if running)
uv run pytest tests/factory/test_entity_walking_di.py -v

# Explicitly use server_0
FV_INSTANCE=server_0 uv run pytest tests/factory/test_entity_walking_di.py -v
```

### Against Local Factorio Client
```bash
# Set FV_INSTANCE to 'client'
FV_INSTANCE=client uv run pytest tests/factory/test_entity_walking_di.py -v
```

## Environment Variable: `FV_INSTANCE`

Controls which Factorio instance to connect to:

| Value | Description | RCON Port | Script Output |
|-------|-------------|-----------|---------------|
| `client` | Local Factorio client | 27100 | `~/.factorio/script-output` |
| `server_0` | Docker server 0 | 27000 | `.fv-output/output_0` |
| `server_1` | Docker server 1 | 27001 | `.fv-output/output_1` |
| (not set) | Auto-detect running instance | varies | varies |

## Prerequisites

### For Local Client Tests
1. **Start Factorio client** with scenario (freeplay or test-ground)
2. **Enable RCON** in `~/.factorio/config/config.ini`:
   ```ini
   [network]
   rcon-port=27100
   rcon-password=factorio
   ```
3. **Install mods**:
   - `fv_embodied_agent`
   - `fv_snapshot`
   
### For Docker Server Tests
1. **Start Docker server**:
   ```bash
   docker-compose up -d factorio_0
   ```
2. **Wait for ready**: ~10 seconds

## Common Test Commands

```bash
# Run all entity walking integration tests
FV_INSTANCE=client uv run pytest tests/factory/test_entity_walking_di.py -v

# Run specific test class
FV_INSTANCE=client uv run pytest tests/factory/test_entity_walking_di.py::TestRemoteViewQueries -v

# Run specific test
FV_INSTANCE=client uv run pytest tests/factory/test_entity_walking_di.py::TestRemoteViewQueries::test_get_entities_returns_walkable_entities -xvs

# Run with verbose output
FV_INSTANCE=client uv run pytest tests/factory/test_entity_walking_di.py -xvs

# Skip integration tests (only unit tests)
FV_INSTANCE=client uv run pytest tests/factory/test_entity_walking_di.py -k "not RemoteViewQueries" -v
```

## Convenience Scripts

Create shell aliases for convenience:

```bash
# Add to ~/.zshrc or ~/.bashrc
alias pytest-client='FV_INSTANCE=client uv run pytest'
alias pytest-server='FV_INSTANCE=server_0 uv run pytest'

# Usage:
pytest-client tests/factory/test_entity_walking_di.py -v
pytest-server tests/factory/test_entity_walking_di.py -v
```

## Troubleshooting

### "No instance detected"
- **Client**: Ensure Factorio is running with RCON enabled
- **Server**: Ensure Docker container is started and healthy

### "Connection refused"
- Check RCON port matches config
- Verify password is correct ("factorio" by default)
- Client: Check `~/.factorio/config/config.ini`
- Server: Check `docker-compose.yml`

### "Failed to place entity"
- **test-ground scenario**: Some positions have collisions
- Tests include try-except to handle this gracefully
- **freeplay scenario**: Should have fewer collisions

### Snapshots not found
- Ensure snapshot directory exists:
  - Client: `~/.factorio/script-output/factoryverse/snapshots`
  - Server: `.fv-output/output_0/factoryverse/snapshots`
- Trigger snapshot with `force_resnapshot()` in test
- Wait 2 seconds after triggering snapshot

## How Instance Detection Works

1. **Check `FV_INSTANCE` env var** - If set, use that instance
2. **Auto-detect** - Poll RCON ports to find running instances:
   - Try client (27100)
   - Try server_0 (27000)
   - Try server_1 (27001), etc.
3. **Return first responsive** - Use first instance that responds

The detection is handled by `FactorioInstanceManager.from_env()` in the test fixtures.

## Example: Testing Against Client

```bash
# 1. Start Factorio client with freeplay
# 2. Enable RCON in config.ini
# 3. Run tests

FV_INSTANCE=client uv run pytest tests/factory/test_entity_walking_di.py -v

# Output will show:
# INFO Using instance from FV_INSTANCE: client
# INFO RCON connected to localhost:27100
# ...
# ====== 17 passed in 3.97s ======
```

## Example: Switching Between Instances

```bash
# Test against client
FV_INSTANCE=client uv run pytest tests/factory/test_entity_walking_di.py -v

# Test against Docker server
FV_INSTANCE=server_0 uv run pytest tests/factory/test_entity_walking_di.py -v

# Let auto-detection choose
uv run pytest tests/factory/test_entity_walking_di.py -v
```
