# Holistic Architecture Analysis: Current State & Expanded Scope

## Executive Summary

This document captures the **expanded scope** beyond the original `INFRA_REFACTOR_PLAN.md`:
1. **Stateful UI** for trajectories and orchestration (NiceGUI-based)
2. **Service-based infrastructure** shared between GUI and CLI
3. **Modularization** of `run_agent.py` - it should NOT own infrastructure
4. **MCP validation** - important but not yet validated
5. **Decoupled observation** - viewers can check status without being in same process

**Key Insight:** The intent is **service-based, modular infrastructure** that can be seamlessly presented through both CLI and UI, enabling orchestration and understanding of what's happening.

---

## Current State: What Exists

### 1. UI Modules ✅

**Location:** `src/FactoryVerse/ui/`

- **`service_manager.py`** - `ServiceManager` (singleton)
  - Wraps: `FactorioClientManager`, `FactorioServerManager`, `DockerComposeManager`, `JupyterManager`
  - Provides: `get_all_statuses()`, `start_client()`, `stop_client()`, `start_docker()`, `stop_docker()`
  - **Can be shared between GUI and CLI** ✅

- **`dashboard.py`** - NiceGUI dashboard
  - Uses `ServiceManager` to show service status
  - Real-time updates via auto-refresh timer
  - **Service orchestration UI** ✅

- **`agent_viewer.py`** - NiceGUI trajectory viewer
  - Reads from `TrajectoryReader` (file-based) or `TrajectoryManager` (live)
  - Shows turns, tool calls, statistics
  - **Stateful UI for trajectories** ✅

### 2. Session/Trajectory Infrastructure ✅

**Location:** `src/FactoryVerse/infra/session/`

- **`trajectory.py`** - File-based event streaming
  - `TrajectoryWriter`: Append events to `trajectory.jsonl`
  - `TrajectoryReader`: Read/tail events, reconstruct turn state
  - `TurnData`: Shared structure for CLI/GUI consumers
  - **Enables decoupled observation** ✅

- **`lifecycle.py`** - Session state management
  - `SessionLifecycle`: Manages `session.json` for tracking live/complete/orphaned status
  - Heartbeat updates for liveness detection
  - Orphan detection (PID + heartbeat timeout)
  - **Enables decoupled status checking** ✅

- **`file_manager.py`** - Session directory management
  - `FileManager`: Creates session directories, manages paths
  - `SessionPaths`: Path structure for sessions

### 3. Service-Based Infrastructure (Partial) ⚠️

**What's Service-Based:**
- `ServiceManager` - Orchestrates services (client, docker, instances)
- Can be used by both GUI (`dashboard.py`) and CLI

**What's NOT Service-Based:**
- **Agent orchestration** - `run_agent.py` owns too much
- **Session creation** - `run_agent.py` creates sessions directly
- **Agent lifecycle** - No unified `AgentService` or `AgentOrchestratorService`

### 4. run_agent.py Issues ❌

**Current Problems:**

1. **Owns too much infrastructure:**
   - RCON validation (`get_rcon_config()`, `validate_rcon_connection()`)
   - UDP port validation (`validate_udp_port()`)
   - Logging setup (file handlers, root logger configuration)
   - Model selection (interactive prompts)
   - Session creation (uses old `SessionManager` from `infra/llm`)
   - Runtime initialization (uses old `FactoryVerseRuntime`)

2. **Uses old infrastructure:**
   ```python
   from FactoryVerse.agent_runtime import FactoryVerseRuntime  # OLD
   from FactoryVerse.infra.llm.session_manager import SessionManager  # OLD
   ```

3. **Creates adapters (interface mismatch):**
   ```python
   class SessionRuntimeAdapter:  # Shouldn't need this
       """Adapter to make FactoryVerseSession compatible with RuntimeProtocol."""
   ```

4. **Monolithic structure:**
   - 530 lines of code
   - Mixes CLI concerns with infrastructure concerns
   - Hard to test, hard to reuse

**What it SHOULD be:**
- Thin wrapper that calls service-based infrastructure
- Minimal logic - just argument parsing and service calls
- All infrastructure owned by services

### 5. CLI Integration ⚠️

**Current State:**
- `cli.py` has `cmd_agent()` that uses `FactoryVerseSession` ✅
- But `run_agent.py` (standalone script) still exists and uses old infrastructure ❌
- Two different entry points with different implementations

**What's Needed:**
- Single unified agent orchestration service
- Both CLI and `run_agent.py` should use the same service
- Or `run_agent.py` should be removed and CLI should be the only entry point

### 6. MCP Status ⚠️

**Current State:**
- MCP server exists at `mcp_server/server.py`
- Uses `infra/llm/boilerplate` (old paths) ❌
- **Not validated** - important for development but not tested

**What's Needed:**
- Update MCP to use new infrastructure paths
- Validate that MCP works with new service-based approach
- Ensure MCP can also use shared services

---

## Architecture Gaps

### Gap 1: No Unified Agent Service ❌

**Problem:** Agent orchestration is scattered:
- `run_agent.py` has its own logic
- `cli.py` has `cmd_agent()` with different logic
- No shared service that both can use

**What's Needed:**
```python
# infra/services/agent_service.py (or similar)
class AgentService:
    """Service for agent orchestration - shared by CLI and GUI."""
    
    async def create_session(
        self,
        model: str,
        mode: str,
        instance: Optional[str] = None,
        agent_id: str = "agent_1",
    ) -> AgentSession:
        """Create and start an agent session."""
        # Uses FactoryVerseSession, TrajectoryWriter, SessionLifecycle
        # Returns session object that can be observed via UI
        
    async def run_turn(self, session_id: str, user_message: str) -> str:
        """Run a single turn in a session."""
        
    async def stop_session(self, session_id: str) -> None:
        """Stop a running session."""
        
    def get_session_status(self, session_id: str) -> SessionStatus:
        """Get current status of a session."""
        
    def list_sessions(self) -> List[AgentSession]:
        """List all sessions (running, complete, orphaned)."""
```

**Benefits:**
- CLI and GUI can both use the same service
- `run_agent.py` becomes a thin wrapper
- Easy to test, easy to extend

### Gap 2: run_agent.py Owns Infrastructure ❌

**Problem:** `run_agent.py` has 530 lines and owns:
- RCON validation
- UDP port validation
- Logging setup
- Model selection
- Session creation
- Runtime initialization

**What's Needed:**
- Extract RCON validation → `infra/services/connection_service.py`
- Extract UDP port validation → `infra/services/port_service.py` (or existing `port_utils`)
- Extract logging setup → `infra/services/logging_service.py`
- Extract model selection → `infra/services/model_service.py`
- Extract session creation → `AgentService.create_session()`
- Extract runtime initialization → `AgentService` (uses `FactoryVerseSession`)

**Result:** `run_agent.py` becomes ~50 lines:
```python
async def main():
    parser = argparse.ArgumentParser(...)
    args = parser.parse_args()
    
    service = AgentService()
    
    if args.list_sessions:
        sessions = service.list_sessions()
        # Display sessions
        return
    
    session = await service.create_session(
        model=args.model,
        mode=args.mode,
        instance=args.instance,
    )
    
    if args.mode == "assisted":
        await run_assisted_interactive(service, session)
    else:
        await run_autonomous(service, session, args.max_turns)
```

### Gap 3: Interface Mismatches ❌

**Problem:** `SessionRuntimeAdapter` exists because:
- `AgentOrchestrator` expects `RuntimeProtocol`
- `FactoryVerseSession` doesn't implement `RuntimeProtocol`
- Adapter bridges the gap

**What's Needed:**
- Either: Make `FactoryVerseSession` implement `RuntimeProtocol`
- Or: Make `AgentOrchestrator` accept `FactoryVerseSession` directly
- Or: Create a proper service layer that abstracts this

### Gap 4: Duplicate Session Management ❌

**Problem:** Two different session management systems:
1. `infra/llm/session_manager.py` (old) - Used by `run_agent.py`
2. `infra/session/` (new) - Used by CLI and trajectory system

**What's Needed:**
- Remove `infra/llm/session_manager.py`
- Consolidate on `infra/session/` modules
- Update `run_agent.py` to use new system

### Gap 5: MCP Not Validated ⚠️

**Problem:**
- MCP server exists but uses old paths
- Not validated with new infrastructure
- Important for development but not tested

**What's Needed:**
- Update MCP to use new paths (`infra/boilerplate/`, not `infra/llm/boilerplate/`)
- Validate MCP works with service-based approach
- Ensure MCP can also use shared services

---

## Proposed Architecture

### Service Layer

```
infra/services/
├── __init__.py
├── agent_service.py          # Agent orchestration (shared by CLI/GUI)
├── connection_service.py      # RCON validation, connection management
├── model_service.py           # Model selection, listing
├── port_service.py            # UDP port validation, allocation
└── logging_service.py         # Logging setup per session
```

### Agent Service Interface

```python
class AgentService:
    """Unified service for agent orchestration."""
    
    def __init__(self):
        self._sessions: Dict[str, AgentSession] = {}
        self._lifecycle = SessionLifecycleManager()  # Manages all session lifecycles
    
    async def create_session(
        self,
        model: str,
        mode: str,
        instance: Optional[str] = None,
        agent_id: str = "agent_1",
    ) -> AgentSession:
        """Create and start an agent session.
        
        Returns:
            AgentSession with session_id, trajectory_writer, lifecycle, etc.
        """
        # 1. Create session directory (FileManager)
        # 2. Create FactoryVerseSession (execution + domain)
        # 3. Create TrajectoryWriter
        # 4. Create SessionLifecycle
        # 5. Initialize AgentOrchestrator
        # 6. Start session
        # 7. Return AgentSession object
        
    async def run_turn(self, session_id: str, user_message: str) -> str:
        """Run a single turn in a session."""
        session = self._sessions[session_id]
        return await session.orchestrator.run_turn(user_message)
    
    async def stop_session(self, session_id: str) -> None:
        """Stop a running session."""
        session = self._sessions[session_id]
        await session.stop()
        self._lifecycle.complete(session.session_dir, session.turn_number)
    
    def get_session_status(self, session_id: str) -> SessionStatus:
        """Get current status of a session."""
        session = self._sessions.get(session_id)
        if session:
            return SessionStatus.RUNNING
        # Check via SessionLifecycle for orphaned/complete
        return self._lifecycle.get_status(session_id)
    
    def list_sessions(self) -> List[AgentSessionInfo]:
        """List all sessions (running, complete, orphaned)."""
        # Combines in-memory sessions + file-based sessions via SessionLifecycle
```

### AgentSession Object

```python
@dataclass
class AgentSession:
    """Represents an active agent session."""
    
    session_id: str
    session_dir: Path
    session: FactoryVerseSession  # Execution + domain
    orchestrator: AgentOrchestrator
    trajectory_writer: TrajectoryWriter
    lifecycle: SessionLifecycle
    model: str
    mode: str
    turn_number: int = 0
    
    async def stop(self) -> None:
        """Stop the session."""
        await self.session.stop()
        self.lifecycle.complete(self.session_dir, self.turn_number)
```

### Usage Patterns

**CLI:**
```python
# cli.py
def cmd_agent(args):
    service = AgentService()
    session = await service.create_session(...)
    await run_interactive(service, session)
```

**GUI:**
```python
# ui/agent_orchestrator.py (new)
class AgentOrchestratorUI:
    def __init__(self):
        self.service = AgentService()
    
    async def start_session(self, model, mode):
        session = await self.service.create_session(model, mode)
        # Show in UI, connect to trajectory viewer
```

**run_agent.py (thin wrapper):**
```python
# scripts/run_agent.py
async def main():
    args = parse_args()
    service = AgentService()
    
    if args.list_sessions:
        sessions = service.list_sessions()
        display_sessions(sessions)
        return
    
    session = await service.create_session(...)
    await run_mode(service, session, args.mode)
```

**MCP:**
```python
# mcp_server/server.py
class FactoryVerseMCPServer:
    def __init__(self):
        self.agent_service = AgentService()
    
    async def _create_agent_session(self, args):
        session = await self.agent_service.create_session(...)
        return session.session_id
```

---

## Migration Path

### Phase 1: Create Service Layer
1. Create `infra/services/` directory
2. Extract infrastructure from `run_agent.py`:
   - `connection_service.py` - RCON validation
   - `model_service.py` - Model selection
   - `port_service.py` - UDP port validation
3. Create `agent_service.py` with basic interface

### Phase 2: Refactor run_agent.py
1. Update `run_agent.py` to use `AgentService`
2. Remove infrastructure ownership from `run_agent.py`
3. Make `run_agent.py` a thin wrapper (~50 lines)

### Phase 3: Integrate CLI
1. Update `cli.py` `cmd_agent()` to use `AgentService`
2. Ensure CLI and `run_agent.py` use same service

### Phase 4: Integrate GUI
1. Create `ui/agent_orchestrator.py` that uses `AgentService`
2. Connect to `agent_viewer.py` for trajectory viewing
3. Enable starting/stopping sessions from UI

### Phase 5: Update MCP
1. Update MCP to use new paths
2. Update MCP to use `AgentService`
3. Validate MCP works with new infrastructure

### Phase 6: Cleanup
1. Remove old `infra/llm/session_manager.py`
2. Remove old `infra/llm/` files
3. Remove `SessionRuntimeAdapter` (fix interface mismatch)

---

## Validation Checklist

### Service-Based Infrastructure ✅/❌
- [ ] `AgentService` exists and is used by CLI
- [ ] `AgentService` exists and is used by GUI
- [ ] `AgentService` exists and is used by `run_agent.py`
- [ ] `AgentService` exists and is used by MCP
- [ ] Infrastructure services (connection, model, port, logging) are extracted
- [ ] No infrastructure ownership in `run_agent.py`

### UI Integration ✅/❌
- [ ] GUI can start agent sessions via `AgentService`
- [ ] GUI can view trajectories via `TrajectoryReader`
- [ ] GUI can check session status via `SessionLifecycle`
- [ ] GUI can stop sessions via `AgentService`
- [ ] Real-time updates work (trajectory streaming, status polling)

### Decoupled Observation ✅/❌
- [ ] `TrajectoryReader` can read from file without being in same process
- [ ] `SessionLifecycle` can detect orphaned sessions
- [ ] Multiple viewers can observe same session
- [ ] Status checking works across process boundaries

### MCP Validation ✅/❌
- [ ] MCP uses new infrastructure paths
- [ ] MCP can create sessions via `AgentService`
- [ ] MCP can execute code in sessions
- [ ] MCP works for development workflows

---

## Key Principles

1. **Service-Based:** All infrastructure is in services, not in scripts
2. **Shared:** Services can be used by CLI, GUI, MCP, tests
3. **Modular:** Each service has a single responsibility
4. **Observable:** State is file-based (trajectory.jsonl, session.json) for decoupled observation
5. **No Ownership:** Scripts don't own infrastructure, they call services

---

## Questions for Discussion

1. **Should `run_agent.py` be removed entirely?** Or kept as a thin wrapper?
2. **Should MCP be prioritized?** It's important for development but not validated
3. **How should autonomous mode work?** Currently it's a placeholder in `run_agent.py`
4. **Should there be a unified `AgentService` or separate services?** (e.g., `SessionService`, `OrchestrationService`)
5. **How should trajectory streaming work?** Currently `TrajectoryReader` polls - should it use file watching?
