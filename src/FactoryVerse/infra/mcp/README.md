# FactoryVerse MCP Servers

Two MCP servers for different use cases:

| Server | Command | Purpose |
|--------|---------|---------|
| **Development** | `factoryverse-mcp` | Full toolset for codebase work, testing, infrastructure |
| **Gameplay** | `factoryverse-play` | Minimal tools for AI agents playing Factorio |

## Quick Start

```bash
# Development server (20+ tools)
uv run factoryverse-mcp --help

# Gameplay server (2 tools: execute + query)
uv run factoryverse-play --help
```

## Server Comparison

### Development Server (`factoryverse-mcp`)

For working on the FactoryVerse codebase:

- **Testing**: `factoryverse_run_test`
- **Sessions**: `create_session`, `execute_in_session`, `reload_session`, `destroy_session`
- **Infrastructure**: `server_start`, `server_stop`, `client_start`, `client_stop`
- **Instances**: `list_instances`, `instance_status`
- **Hot-reload**: `reload_python`, `server_reload`
- **Debugging**: `execute_code`, `inspect_inventory`, `add_inventory`

### Gameplay Server (`factoryverse-play`)

For AI agents playing Factorio:

| Tool | Description |
|------|-------------|
| `execute` | Run Python code with access to all runtime components (walking, crafting, placement, etc.) |
| `query` | Run DuckDB SQL queries against game state |

**Key design principles:**
- Agents never see infrastructure details (sessions, tiers, connections)
- Lazy initialization on first tool call
- Persistent runtime state across calls
- Clean error messages (no tracebacks)

**Prerequisite**: Factorio must be running. Start it via CLI or development MCP server first.

## Claude Code Configuration

The repo includes two pre-configured MCP config files:

| File | Purpose | Launch Command |
|------|---------|----------------|
| `mcp-dev.json` | Development/codebase work | `claude --mcp-config ./mcp-dev.json` |
| `mcp-gameplay.json` | AI agent gameplay | `claude --mcp-config ./mcp-gameplay.json` |

### Usage

```bash
# Development session - full toolset
claude --mcp-config ./mcp-dev.json

# Gameplay session - minimal tools for agent runs
claude --mcp-config ./mcp-gameplay.json

# Strict mode (ignore other MCP configs)
claude --strict-mcp-config --mcp-config ./mcp-gameplay.json
```

### Alternative: Combined config (`.mcp.json`)

If you want both servers available and toggle via `/mcp`:

```json
{
  "mcpServers": {
    "factoryverse": {
      "command": "uv",
      "args": ["run", "factoryverse-mcp"],
      "cwd": "/path/to/FactoryVerse"
    },
    "factoryverse-play": {
      "command": "uv",
      "args": ["run", "factoryverse-play"],
      "cwd": "/path/to/FactoryVerse"
    }
  }
}
```

### Option 3: CLI management

```bash
# Add servers
claude mcp add --transport stdio --scope project factoryverse -- uv run factoryverse-mcp
claude mcp add --transport stdio --scope project fv-play -- uv run factoryverse-play

# List configured servers
claude mcp list

# Remove a server
claude mcp remove fv-play
```

## Switching Between Servers

### Method 1: `/mcp` command (in Claude Code)

Use `/mcp` within Claude Code to view and toggle servers interactively.

### Method 2: `disabledMcpServers` in `~/.claude.json`

Servers can be disabled per-project. Edit `~/.claude.json`:

```json
{
  "disabledMcpServers": {
    "/path/to/FactoryVerse": ["factoryverse"]
  }
}
```

This keeps `factoryverse-play` enabled while disabling the development server.

### Method 3: Launch flags

```bash
# Use only gameplay server
claude --strict-mcp-config --mcp-config ./mcp-gameplay.json

# Note: --strict-mcp-config has a known bug where it doesn't
# override disabledMcpServers. You may need to manually edit
# ~/.claude.json if servers remain disabled.
```

### Method 4: Environment variables

```bash
# Increase timeout for slow server startup
MCP_TIMEOUT=15000 claude

# Limit tool output size
MAX_MCP_OUTPUT_TOKENS=50000 claude
```

## Typical Workflows

### Development Session

1. Start Factorio: `uv run fv client launch --scenario test-ground`
2. Launch Claude Code with dev server: `claude --mcp-config ./mcp-dev.json`
3. Use full toolset for testing, debugging, infrastructure management

### Gameplay Session

1. Start Factorio (via CLI or manually)
2. Launch Claude Code with gameplay server: `claude --mcp-config ./mcp-gameplay.json`
3. AI agent uses only `execute` and `query` tools
4. No infrastructure knowledge required - just plays the game

### Mixed Session

1. Configure both servers in `.mcp.json`
2. Use `/mcp` in Claude Code to enable/disable as needed
3. Development server for setup, gameplay server for agent runs

## Troubleshooting

### "Game not running" error

The gameplay server requires Factorio to be running. Start it first:
```bash
uv run fv client launch --scenario test-ground
# or
uv run fv server start --num 1 --scenario test-ground
```

### Server not appearing in Claude Code

1. Check config path is absolute or uses `${workspaceFolder}`
2. Verify `uv run factoryverse-play --help` works from that directory
3. Check `claude mcp list` output
4. Look for errors in Claude Code's MCP logs

### Timeout on first tool call

The gameplay server initializes lazily. First call may take a few seconds.
Increase timeout if needed:
```bash
MCP_TIMEOUT=15000 claude
```

## References

- [Claude Code MCP Documentation](https://code.claude.com/docs/en/mcp)
- [MCP Protocol Specification](https://modelcontextprotocol.io/docs)
- [Known issue: --strict-mcp-config doesn't override disabledMcpServers](https://github.com/anthropics/claude-code/issues/14490)
