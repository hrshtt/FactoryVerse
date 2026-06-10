# FactoryVerse CLI and UI Redesign Plan

**Date**: 2026-01-16  
**Status**: Design Phase  
**Purpose**: Design document for rethinking FactoryVerse's command-line interface and user interaction model

---

## Executive Summary

This document captures the design discussions around FactoryVerse's CLI structure, code organization, and user interface approach. The primary insight is that the current client/server distinction in commands may not align with user mental models, and that a web-based UI would significantly improve the orchestration experience for managing multiple services (client, server, agent, MCP).

---

## Current State Analysis

### Command Structure

The current CLI is organized around **client vs server** distinction:

**Client Commands:**
- `fv client start/stop/restart/status/log/dump-data`

**Server Commands:**
- `fv server start/stop/restart/list/logs/instance/list-scenarios`

**Other Commands:**
- `fv data prune/refresh`
- `fv instance list/active`
- `fv prompts generate/api/schema`
- `fv agent` (launch)
- `fv mcp` (launch)

### Code Organization Issues

1. **Significant Duplication** (~210 lines):
   - Hash calculation functions duplicated between client and server setup
   - Mod list management duplicated
   - Mod copying logic duplicated
   - Mod preparation flow duplicated

2. **Unnecessary Coupling**:
   - `FactorioClientManager` creates `FactorioServerManager` just to get `scenarios_dir`
   - Client and server setup code are separate but do identical work

3. **Complexity**:
   - `fv server start` does BOTH client and server setup (intentional but confusing)
   - Work directory derivation logic seems legacy
   - Deprecated scenario cleanup in hot path

### User Mental Model Mismatch

The current structure assumes users think in terms of "client operations" vs "server operations", but the actual user flows are:

1. **Setup** (prepare environment, can be dry-run):
   - MCP: No setup needed (just launch)
   - Client: Can be dry-run (human launches later)
   - Server: Not really dry-run (system requires servers running)
   - Agent: Minimal setup (check keys, verify config)

2. **Launch** (actually start things):
   - Client launch
   - Server launch
   - Agent launch
   - MCP launch

3. **Status/Monitoring**:
   - Check what's running
   - View logs
   - Instance discovery

---

## Design Intentions

### 1. Setup vs Launch Distinction

**Core Insight**: Users don't think "I want to do a client operation" - they think "I want to set up the client" or "I want to launch the client". The distinction between setup and launch is more fundamental than client vs server.

**Design Principle**: Commands should reflect user intent, not implementation details.

**Proposed Structure**:
```
fv setup <target> [options]     # Prepare environment (dry-run possible)
fv launch <target> [options]    # Actually start things
fv status [target]              # Check what's running
fv stop <target>                # Stop running things
```

**Benefits**:
- Clearer mental model
- Less duplication (setup is implicit in launch)
- Better flow: `setup client --dry-run` → human launches → `status client`
- Consistent pattern across all targets

### 2. Code Consolidation

**Core Insight**: Client and server mod setup do identical work, just targeting different directories. The duplication is unnecessary and makes maintenance harder.

**Design Principle**: Extract shared logic into reusable components. Separate concerns by operation (setup/launch) not by target (client/server).

**Proposed Approach**:
- Create `ModManager` class that takes target directory as parameter
- Both `setup_client()` and `server_mgr.prepare_mods()` use same `ModManager`
- Eliminates ~210 lines of duplication
- Single source of truth for mod logic

**What Stays Separate**:
- Client-specific: Platform detection, executable finding, process lifecycle
- Server-specific: Docker Compose generation, container management
- Different target directories (client: `~/.factorio/mods`, server: Docker volume)

### 3. Web UI for Orchestration

**Core Insight**: Managing multiple services (client, server, agent, MCP) with complex state requires visual feedback and stateful interaction. CLI commands require users to remember state and manually check status.

**Design Principle**: Use the right tool for the job. CLI for automation, Web UI for interactive management.

**Why Web UI Over TUI**:
1. **State Visibility**: Real-time dashboard showing all services at once
2. **Better UX**: Visual indicators, one-click operations, contextual error messages
3. **Extensibility**: Easy to add graphs, metrics, visualizations later
4. **Remote Access**: Access from any device, shareable links
5. **Industry Standard**: Docker, Kubernetes, LangChain all use web UIs

**Why Not TUI**:
1. Limited screen real estate
2. Still requires polling/refreshing
3. Less intuitive interaction model
4. TUI frameworks less mature than web frameworks

**Hybrid Approach**:
- **CLI**: Keep for automation, scripts, CI/CD, power users
- **Web UI**: Add for interactive management, visual feedback, state tracking
- **Shared Backend**: Both CLI and Web UI call same underlying logic

---

## Proposed Architecture

### Command Structure

**Setup Commands** (prepare, can be dry-run):
```bash
fv setup client [--scenario SCENARIO] [--force] [--dry-run]
  # Sets up client mods/scenarios
  # --dry-run: Just check, don't copy (for human to launch later)

fv setup server [--scenario SCENARIO] [--force] [--num N]
  # Sets up server mods (always launches, no dry-run)

fv setup agent [--check-keys]
  # Minimal setup: verify API keys, check config
```

**Launch Commands** (actually start):
```bash
fv launch client [--scenario SCENARIO] [--save-file PATH] [--new-map] [options]
  # Launches Factorio client (implicitly does setup if needed)

fv launch server [--scenario SCENARIO] [--num N] [options]
  # Launches servers (implicitly does setup if needed)

fv launch agent [--model MODEL] [--mode MODE] [options]
  # Launches agent (implicitly does setup if needed)

fv launch mcp
  # Launches MCP server (no setup needed)
```

**Status Commands**:
```bash
fv status                    # Show all running things
fv status client             # Client status
fv status server             # Server status
fv status agent              # Agent status
```

**Stop Commands**:
```bash
fv stop client [--force]
fv stop server
fv stop agent
fv stop all                  # Stop everything
```

**Utility Commands** (unchanged):
```bash
fv logs client|server [--follow]
fv data prune|refresh
fv scenarios list
fv prompts generate|api|schema
```

### Web UI Structure

**Dashboard View**:
- Real-time status of all services (client, server, agent, MCP)
- Visual indicators (green/red) for running/stopped
- One-click start/stop/restart buttons
- Service details (PID, scenario, ports, etc.)

**Service Management**:
- Individual service cards with controls
- Setup wizards for complex configurations
- Log viewer with real-time updates
- Error messages in context

**Future Extensions**:
- Metrics/graphs
- Agent activity visualization
- Screenshot integration
- Real-time game state visualization

### Code Organization

**Shared Backend Logic**:
```
infra/
  mod_manager.py          # Shared mod management (hash checking, copying)
  setup.py                # Setup operations (client, server, agent)
  launch.py               # Launch operations (client, server, agent)
  status.py               # Status checking (all services)
```

**Target-Specific Logic**:
```
infra/
  client/
    lifecycle.py          # Client process management (PID tracking)
    executable.py         # Client executable finding
  server/
    docker.py             # Docker Compose generation
    containers.py         # Container management
  agent/
    orchestration.py      # Agent lifecycle
```

---

## Open Questions and Unresolved Decisions

### 1. Migration Strategy

**Question**: How do we migrate from current commands to new structure?

**Options**:
- A) Add new commands, deprecate old ones, remove after migration period
- B) Keep old commands as aliases to new ones
- C) Big bang replacement

**Considerations**:
- Backward compatibility for existing scripts
- User education/communication
- Timeline for deprecation

**Status**: Open

### 2. Web UI Technology Stack

**Question**: What technologies should we use for the web UI?

**Options**:
- A) FastAPI + React/Vue (full SPA)
- B) FastAPI + htmx (simpler, server-rendered)
- C) FastAPI + Jinja2 templates (minimal JS)
- D) Something else

**Considerations**:
- Development speed
- Maintenance burden
- Real-time updates (WebSocket vs polling)
- Team expertise

**Status**: Open

### 3. Web UI Deployment

**Question**: How should the web UI be accessed?

**Options**:
- A) Always running on localhost (auto-start with CLI)
- B) Explicit start command (`fv ui start`)
- C) Embedded in existing services (e.g., Jupyter)

**Considerations**:
- Resource usage
- Security (local only vs network accessible)
- User expectations

**Status**: Open

### 4. State Management

**Question**: How should we track service state?

**Options**:
- A) File-based (PID files, state JSON) - current approach
- B) Database (SQLite)
- C) In-memory with persistence
- D) Hybrid (file-based for CLI, database for UI)

**Considerations**:
- Consistency between CLI and UI
- Performance
- Reliability

**Status**: Open

### 5. Setup Dry-Run Implementation

**Question**: How should dry-run work for client setup?

**Options**:
- A) Check everything but don't copy files
- B) Show what would be done (diff view)
- C) Validate configuration only

**Considerations**:
- User expectations
- Implementation complexity
- Value provided

**Status**: Open

### 6. Agent Setup Scope

**Question**: What should `fv setup agent` actually do?

**Current Understanding**: Minimal - check API keys, verify config

**Open Questions**:
- Should it validate model availability?
- Should it check Factorio instance connectivity?
- Should it prepare any local state?

**Status**: Open

### 7. CLI vs Web UI Feature Parity

**Question**: Should all features be available in both CLI and Web UI?

**Options**:
- A) Full parity (everything in both)
- B) CLI for automation, UI for interactive (some features UI-only)
- C) CLI for power users, UI for common operations

**Considerations**:
- Development effort
- User needs
- Maintenance burden

**Status**: Open

### 8. Web UI Authentication

**Question**: Should the web UI have authentication?

**Options**:
- A) No auth (localhost only, trust local network)
- B) Simple token-based auth
- C) Full authentication system

**Considerations**:
- Security requirements
- Use case (single user vs team)
- Complexity

**Status**: Open

### 9. Real-Time Updates

**Question**: How should real-time updates work in the web UI?

**Options**:
- A) WebSocket for push updates
- B) Polling (simpler, less efficient)
- C) Server-Sent Events (middle ground)

**Considerations**:
- Implementation complexity
- Resource usage
- User experience

**Status**: Open

### 10. Code Consolidation Scope

**Question**: How far should we go with code consolidation?

**Current Plan**: Consolidate mod management (~210 lines)

**Open Questions**:
- Should we consolidate path resolution logic?
- Should we consolidate scenario management?
- Should we create a unified "service manager" abstraction?

**Considerations**:
- Balance between DRY and over-abstraction
- Maintainability
- Testability

**Status**: Open

---

## Implementation Phases (High-Level)

### Phase 1: Code Consolidation
- Create `ModManager` class
- Refactor client and server setup to use shared logic
- Fix duplicate print statement
- Remove deprecated scenario cleanup
- **Goal**: Eliminate duplication, improve maintainability

### Phase 2: CLI Reorganization
- Add new `setup`/`launch`/`status`/`stop` commands
- Keep old commands working (with deprecation warnings)
- Update documentation
- **Goal**: Better command structure, backward compatible

### Phase 3: Web UI Foundation
- FastAPI backend with basic endpoints
- Simple HTML/JS frontend
- Basic start/stop/status functionality
- **Goal**: Proof of concept, validate approach

### Phase 4: Web UI Enhancement
- Real-time updates (WebSocket or polling)
- Logs viewer
- Setup wizards
- **Goal**: Production-ready interactive management

### Phase 5: Advanced Features
- Metrics/graphs
- Agent activity visualization
- Screenshot integration
- **Goal**: Rich user experience

---

## Design Principles

1. **User Intent Over Implementation**: Commands should reflect what users want to do, not how it's implemented
2. **Right Tool for the Job**: CLI for automation, Web UI for interactive management
3. **DRY but Not Over-Abstracted**: Consolidate shared logic, but keep concerns separated
4. **Backward Compatibility**: Don't break existing workflows during migration
5. **Progressive Enhancement**: Start simple, add features based on feedback
6. **State Visibility**: Users should always know what's running without manual checking

---

## Success Criteria

1. **Reduced Complexity**: Fewer commands, clearer structure
2. **Better UX**: Users can manage services without remembering state
3. **Less Duplication**: Shared logic in one place
4. **Extensibility**: Easy to add new services/features
5. **Maintainability**: Easier to understand and modify code

---

## References

- Current CLI implementation: `src/FactoryVerse/cli.py`
- Client setup: `src/FactoryVerse/infra/factorio_client_setup.py`
- Client manager: `src/FactoryVerse/infra/factorio_client_manager.py`
- Server manager: `src/FactoryVerse/infra/docker/factorio_server_manager.py`
- Related discussions: Code duplication analysis, CLI flow analysis

---

## Notes

- This document focuses on **design intentions**, not implementation details
- Implementation details should be captured in separate implementation plans
- This document should be updated as decisions are made on open questions
- Regular review recommended to ensure design still aligns with user needs
