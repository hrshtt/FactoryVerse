# FactoryVerse Environment Module Design

## Executive Summary

The `environment` module is the **canonical orchestrator** for FactoryVerse. It provides a principled, tiered approach to composing the complete runtime stack — from Factorio infrastructure to generative agent interaction.

**Key distinction**: Environment is an **orchestrator**, not an implementer. It doesn't own the technical implementations — it composes and coordinates existing modules (Docker, RCON, agent modules, LLM clients) into a coherent, verifiable stack.

This is not a testing utility. This is THE way to use FactoryVerse.

---

## Design Philosophy

### What Environment Is

- **An orchestrator**: Composes existing implementations into a verifiable stack
- **A composition root**: The single place where the system is assembled
- **A contract enforcer**: Ensures each tier is ready before the next proceeds
- **A lifecycle manager**: Handles startup, shutdown, and reset across tiers

### What Environment Is NOT

- **Not an implementer**: Doesn't own RCON, DuckDB, LLM clients — uses them
- **Not a view layer**: CLI, NiceGUI are *consumers* of Environment, not part of it
- **Not a framework**: Doesn't impose patterns on domain code

### Core Principles

1. **Single Composition Root**: All FactoryVerse setup flows through `environment`. No scattered setup code.

2. **Tiered Dependencies**: Each tier depends on lower tiers. You cannot have tier 4 without tier 3.

3. **Explicit Contracts**: Each tier has verification checks. Transitions are validated.

4. **Selective Loading**: Request only what you need. Tests load subset, agent runs load full stack.

5. **Intelligent Reloading**: Reset at any tier boundary. Lower tiers remain stable.

6. **Configuration, Not Code Paths**: Client vs server, duckdb vs no-duckdb — these are configuration choices, not separate implementations.

---

## Tier Architecture

Environment orchestrates **tiers 1-6**. Views (CLI, NiceGUI) are **external consumers**.

```
┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐
│                        CONSUMERS (outside Environment)                     │
│                          CLI, NiceGUI, External UI                         │
└ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘
                                      │
                                      ▼ uses
╔═════════════════════════════════════════════════════════════════════════════╗
║                           ENVIRONMENT (Orchestrator)                        ║
╠═════════════════════════════════════════════════════════════════════════════╣
║  TIER 6: GENERATIVE/INTERACTIVE LAYER                                      ║
║          Autonomous | Assisted | MCP Server                                 ║
╠═════════════════════════════════════════════════════════════════════════════╣
║  TIER 5: AGENT SPECIFICATION                                                ║
║          System Prompt | Task Definition                                    ║
╠═════════════════════════════════════════════════════════════════════════════╣
║  TIER 4: FACTORYVERSE RUNTIME                                               ║
║          Agent Modules (remote_view, embodied_actions, etc.)                ║
╠═════════════════════════════════════════════════════════════════════════════╣
║  TIER 3: FACTORYVERSE INFRA                                                 ║
║          Python Runtime + RCON + UDP Listeners                              ║
╠═════════════════════════════════════════════════════════════════════════════╣
║  TIER 2: FACTORIO SETTINGS                                                  ║
║          Scenario | Save | Game State                                       ║
╠═════════════════════════════════════════════════════════════════════════════╣
║  TIER 1: FACTORIO INFRA                                                     ║
║          Factorio + Mods (Client | Server | Both)                           ║
╚═════════════════════════════════════════════════════════════════════════════╝
```

---

## Tier Definitions

### Tier 1: Factorio Infra

**What it is**: A Factorio installation with our two mods loaded (`factorio-rcon-interface`, `fv-embodied-agent`).

**Variants**:
- `1a. CLIENT`: Local Factorio client application
- `1b. SERVER`: Docker-based headless server (one or more)
- `1c. CLIENT_AND_SERVER`: Client connected to server

**Contract**:
- Factorio executable exists and is runnable
- Required mods are installed
- Network ports are available (RCON, UDP)

**Verification**:
```python
tier1.is_ready() -> TierStatus:
    - factorio_installed: bool
    - mods_installed: bool
    - ports_available: Dict[str, bool]  # {"rcon": True, "udp": True}
```

**Lifecycle**:
- `start()`: Launch Factorio (client or container)
- `stop()`: Terminate gracefully
- `reset()`: Stop and restart

---

### Tier 2: Factorio Settings

**What it is**: A specific scenario or save running on the Factorio runtime.

**Configuration**:
- `scenario: str` — Scenario to load (e.g., "freeplay", "lab")
- `save_path: Optional[Path]` — Existing save to load
- `seed: Optional[int]` — World generation seed
- `settings: Dict` — Map generation settings

**Contract**:
- Factorio is running (Tier 1 complete)
- Scenario/save is loaded
- Game is in a playable state (not loading screen)

**Verification**:
```python
tier2.is_ready() -> TierStatus:
    - game_loaded: bool
    - scenario_name: str
    - tick: int  # Game tick (>0 means loaded)
```

**Lifecycle**:
- `load_scenario(name)`: Load scenario
- `load_save(path)`: Load save file
- `reset()`: Reload current scenario/save

---

### Tier 3: FactoryVerse Infra

**What it is**: Python runtime with RCON client and UDP listeners connected to Factorio.

**Variants**:
- `3a. SAME_PROCESS`: Executed in the same Python process (for testing)
- `3b. SEPARATE_PROCESS`: Executed in a subprocess (if needed)
- `3c. JUPYTER`: Executed in Jupyter notebook runtime

**Components**:
- `RCONClient`: Connection to Factorio RCON
- `UDPListener`: Receives async notifications from Lua
- `FactorioInstance`: Abstraction over client/server
- `AgentRegistry`: Persistent agent identity management (see Agent Lifecycle section)

**Contract**:
- Factorio is running with game loaded (Tier 2 complete)
- RCON connection is established
- UDP listener is receiving (if enabled)
- Agent Registry initialized (for agent persistence)

**Verification**:
```python
tier3.is_ready() -> TierStatus:
    - rcon_connected: bool
    - rcon_responsive: bool  # Ping test
    - udp_listening: bool
    - instance_type: Literal["client", "server"]
```

**Lifecycle**:
- `connect()`: Establish RCON + UDP
- `disconnect()`: Close connections
- `reconnect()`: Disconnect and reconnect
- `execute_lua(code)`: Raw Lua execution
- `agent_registry`: Access to AgentRegistry for agent persistence

---

### Tier 4: FactoryVerse Runtime

**What it is**: Python agent modules from `src/FactoryVerse/agent` loaded and connected.

**Variants**:
- `4a. MINIMAL`: Core modules only, no remote_view and DuckDB (only for testing)
- `4c. FULL`: All agent modules including remote_view, etc.

**Components**:
- `AgentRuntime`: The main runtime abstraction
- `SnapshotDatabase`: DuckDB connection (optional)
- `RemoteView`: Entity querying via SQL (requires database)
- `ReachableView`: Entity querying via Lua (no database)
- `EmbodiedActions`: Walking, mining, crafting, etc.
- `AgentProfile`: Persistent agent identity (via Tier 3 AgentRegistry)

**Contract**:
- Python infra connected (Tier 3 complete)
- Requested modules are loaded
- Database synced (if 4b/4c)
- Agent entity created/reconciled with persistent profile

**Verification**:
```python
tier4.is_ready() -> TierStatus:
    - runtime_initialized: bool
    - database_connected: bool  # None if 4a
    - database_synced: bool     # None if 4a
    - modules_loaded: List[str]
    - agent_id: str  # Agent identifier (from profile or config)
```

**Lifecycle**:
- `initialize()`: Create runtime and load modules
  - Reconciles agent identity (see Agent Lifecycle section)
  - Creates new agent or resumes existing agent from profile
- `sync_database()`: Force database sync
- `reload_modules()`: Hot-reload Python modules
- `reset()`: Re-initialize runtime

---

### Tier 5: Agent Specification

**What it is**: System prompt and task definition for the agent.

**Components**:
- `system_prompt: str`: The full system prompt (assembled from templates)
- `task: Optional[Task]`: Specific task definition (future)
- `api_reference: str`: Generated API documentation
- `schema_reference: str`: Database schema documentation

**Contract**:
- Runtime loaded (Tier 4 complete)
- System prompt can be generated from current state
- Task is valid (if provided)

**Verification**:
```python
tier5.is_ready() -> TierStatus:
    - system_prompt_generated: bool
    - prompt_length: int
    - task_defined: bool
    - task_valid: bool
```

**Lifecycle**:
- `generate_prompt()`: Build system prompt from templates + runtime state
- `set_task(task)`: Set the task definition
- `reload()`: Regenerate prompt

---

### Tier 6: Generative/Interactive Layer

**What it is**: The interaction mode — how the agent receives input and produces output.

**Variants**:
- `6a. AUTONOMOUS`: Agent runs continuously, context managed naively
- `6b. ASSISTED`: Single-turn interaction, context managed per-turn
- `6c. MCP_SERVER`: MCP protocol, context managed by external client

**Components**:
- `LLMClient`: Connection to LLM provider
- `AgentOrchestrator`: Turn loop, tool execution
- `TrajectoryManager`: Context compression, history
- `ToolValidator`: Pre-execution validation

**Contract**:
- Agent specification ready (Tier 5 complete)
- LLM client connected and responsive
- Orchestrator configured for mode

**Verification**:
```python
tier6.is_ready() -> TierStatus:
    - llm_connected: bool
    - llm_responsive: bool  # Ping test
    - orchestrator_mode: Literal["autonomous", "assisted", "mcp"]
    - tools_registered: int
```

**Lifecycle**:
- `start_session()`: Begin agent session
- `run_turn(message)`: Execute single turn (assisted)
- `run_loop()`: Execute continuous loop (autonomous)
- `stop()`: End session

---

## Views: Consumers of Environment

Views (CLI, NiceGUI) are **not part of Environment** — they are consumers that use Environment to implement their functionality.

### Relationship

```python
# CLI uses Environment
class CLI:
    def cmd_agent(self, args):
        env = Environment.for_agent(mode=args.mode, provider=args.provider)
        await env.initialize(up_to=Tier.INTERACTION)
        await env.tier6.run_loop()
        await env.shutdown()

# NiceGUI uses Environment
class Dashboard:
    def __init__(self):
        self.env: Optional[Environment] = None
    
    def on_start_session(self, config):
        self.env = Environment(config=config)
        await self.env.initialize(up_to=Tier.RUNTIME)
        self.update_status_display(self.env.status())
```

### What Views Do

- **Create and configure Environments**: Based on user input
- **Display Environment status**: Visualize tier readiness
- **Invoke Environment actions**: Reset tiers, reload modules, run agent turns
- **Observe Environment events**: Subscribe to status changes, trajectory updates

### What Views Don't Do

- **Own any tier logic**: That's Environment's job
- **Directly manipulate tier components**: Always go through Environment API
- **Bypass tier contracts**: Can't access tier 4 if tier 3 isn't ready

---

## Environment API

### Primary Interface

```python
from FactoryVerse.environment import Environment, Tier, Config

# Create environment with configuration
env = Environment(
    config=Config(
        # Tier 1
        infra=InfraConfig(
            mode="client_and_server",  # or "client", "server"
            server_count=1,
        ),
        # Tier 2
        settings=SettingsConfig(
            scenario="freeplay",
            seed=12345,
        ),
        # Tier 3
        python=PythonConfig(
            execution="same_process",  # or "jupyter", "subprocess"
            udp_enabled=True,
        ),
        # Tier 4
        runtime=RuntimeConfig(
            variant="with_remote_view",  # or "minimal", "full"
            agent_id="agent_1",
        ),
        # Tier 5
        specification=SpecificationConfig(
            include_api_reference=True,
            include_schema_reference=True,
            task=None,
        ),
        # Tier 6
        interaction=InteractionConfig(
            mode="autonomous",  # or "assisted", "mcp"
            llm_provider="prime_intellect",
            model="intellect-3",
        ),
        # Note: No tier 7 config — views are external consumers
    )
)

# Initialize up to a specific tier
await env.initialize(up_to=Tier.RUNTIME)  # Tiers 1-4

# Check readiness
status = env.status()
# TierStatus(
#     tier1=Ready(factorio_installed=True, ...),
#     tier2=Ready(game_loaded=True, ...),
#     tier3=Ready(rcon_connected=True, ...),
#     tier4=Ready(runtime_initialized=True, ...),
#     tier5=NotInitialized,
#     tier6=NotInitialized,
# )

# Access tier components
rcon = env.tier3.rcon
runtime = env.tier4.runtime
database = env.tier4.database  # None if variant="minimal"

# Reset a specific tier (and all above it)
await env.reset(from_tier=Tier.PYTHON)  # Resets 3-7, keeps 1-2

# Reload modules at tier 4
env.tier4.reload_modules()

# Full cleanup
await env.shutdown()
```

### Convenience Constructors

```python
# For testing
env = Environment.for_testing(
    tier=Tier.RUNTIME,
    variant="minimal",  # No duckdb
    scenario="lab",
)

# For agent runs
env = Environment.for_agent(
    mode="autonomous",
    provider="anthropic",
    model="claude-sonnet-4-20250514",
)

# For MCP server
env = Environment.for_mcp(
    execution="same_process",
)

# For Jupyter notebook
env = Environment.for_notebook(
    instance="client",
    variant="full",
)
```

---

## Verification Protocol

Each tier implements:

```python
class TierBase(ABC):
    @abstractmethod
    async def verify_prerequisites(self) -> PrerequisiteResult:
        """Check that lower tier is ready."""
        pass
    
    @abstractmethod
    async def initialize(self) -> None:
        """Initialize this tier."""
        pass
    
    @abstractmethod
    async def verify_ready(self) -> TierStatus:
        """Verify this tier is fully operational."""
        pass
    
    @abstractmethod
    async def reset(self) -> None:
        """Reset this tier to initial state."""
        pass
    
    @abstractmethod
    async def shutdown(self) -> None:
        """Shutdown this tier."""
        pass
```

### Transition Contract

Before initializing tier N:
1. `tier_n.verify_prerequisites()` — checks tier N-1 is ready
2. If prerequisites fail, raise `TierPrerequisiteError` with diagnostics
3. `tier_n.initialize()` — perform initialization
4. `tier_n.verify_ready()` — confirm tier is operational
5. If verification fails, raise `TierInitializationError` with diagnostics

This ensures **no tier proceeds without explicit verification** of its dependencies.

---

## MCP Integration

The MCP server uses environment for intelligent session management:

```python
class FactoryVerseMCPServer:
    def __init__(self):
        self._environments: Dict[str, Environment] = {}
    
    async def handle_create_session(self, args) -> Dict:
        env = Environment(config=Config.from_dict(args))
        await env.initialize(up_to=Tier.RUNTIME)
        
        session_id = str(uuid.uuid4())
        self._environments[session_id] = env
        
        return {"session_id": session_id, "status": env.status().to_dict()}
    
    async def handle_reset_tier(self, args) -> Dict:
        env = self._environments[args["session_id"]]
        tier = Tier(args["tier"])
        
        await env.reset(from_tier=tier)
        
        return {"status": env.status().to_dict()}
    
    async def handle_execute(self, args) -> Dict:
        env = self._environments[args["session_id"]]
        
        # Environment knows execution context
        result = env.tier3.execute_lua(args["code"])
        
        return {"result": result}
```

### MCP Tools for Tier Management

```
MCP Tools
├── Session Management
│   ├── create_session(config)      # Initialize environment
│   ├── destroy_session(id)         # Shutdown environment
│   ├── get_session_status(id)      # Full tier status
│   └── list_sessions()             # All active environments
│
├── Tier Control
│   ├── reset_tier(session, tier)   # Reset tier and above
│   ├── reload_modules(session)     # Tier 4 module reload
│   ├── reload_lua(session)         # Tier 2-3 Lua reload
│   └── verify_tier(session, tier)  # Explicit verification
│
├── Execution
│   ├── execute_lua(session, code)  # Tier 3 Lua execution
│   ├── execute_python(session, code) # Tier 4 Python execution
│   └── query_database(session, sql)  # Tier 4 DuckDB query
│
└── Agent Control
    ├── generate_prompt(session)    # Tier 5 prompt generation
    ├── run_turn(session, message)  # Tier 6 single turn
    └── get_trajectory(session)     # Tier 6 history
```

---

## Use Case Mapping

| Use Case | Tier Range | Config Highlights |
|----------|------------|-------------------|
| **Agent Autonomous Run** | 1-6 | `interaction.mode="autonomous"` |
| **Agent Assisted Run** | 1-6 | `interaction.mode="assisted"` |
| **MCP Development** | 1-4 | tier 6 is MCP mode |
| **Jupyter Exploration** | 1-4 | `python.execution="jupyter"` |
| **Integration Test** | 1-4 | `runtime.variant="minimal"`, `python.execution="same_process"` |
| **Unit Test (Mocked Factorio)** | 4 only | Mock tier 3, real tier 4 |
| **CLI Dashboard** | 1-2 | CLI *uses* Environment to manage Factorio infra |
| **NiceGUI Full** | 1-6 | NiceGUI *uses* Environment for all tiers |

---

## Migration Path

### Phase 1: Rename and Restructure (Current → Environment)

1. Create `src/FactoryVerse/environment/` module
2. Move `infra/boilerplate/` content to `environment/tiers/`
3. Update `Scope` enum to `Tier` enum with new values
4. Keep backward compat shim at `infra/boilerplate/` temporarily

### Phase 2: Implement Tier 1-2

1. Factor out Factorio infra management from CLI
2. Create `Tier1Factorio` and `Tier2Settings` classes
3. Add verification protocols

### Phase 3: Refactor Tier 3-4

1. Rename current `Scope.RCON` → `Tier3Python`
2. Rename current `Scope.RUNTIME` → `Tier4Runtime`
3. Add variant support (minimal, full)

### Phase 4: Integrate Tier 5-6

1. Move prompt generation into tier 5
2. Move orchestrator into tier 6
3. Add interaction mode configuration

### Phase 5: Update Views to Use Environment

1. Update CLI to use Environment for all commands
2. Update NiceGUI to use Environment for session management
3. Document view integration patterns

### Phase 6: Cleanup

1. Remove `infra/boilerplate/` backward compat shim
2. Remove `infra/llm/` entirely
3. Update all imports
4. Update documentation

---

## Module Structure

```
FactoryVerse/
├── environment/                    # THE orchestrator (tiers 1-6)
│   ├── __init__.py                 # Environment, Tier, Config
│   ├── config.py                   # Configuration dataclasses
│   ├── status.py                   # TierStatus, verification results
│   │
│   ├── tiers/                      # Tier orchestration (NOT implementation)
│   │   ├── __init__.py
│   │   ├── base.py                 # TierBase ABC
│   │   ├── tier1_factorio.py       # Orchestrates Docker, client detection
│   │   ├── tier2_settings.py       # Orchestrates scenario/save loading
│   │   ├── tier3_python.py         # Orchestrates RCON + UDP
│   │   ├── tier4_runtime.py        # Orchestrates agent module loading
│   │   ├── tier5_specification.py  # Orchestrates prompt generation
│   │   └── tier6_interaction.py    # Orchestrates LLM interaction
│   │
│   └── testing/                    # Test utilities
│       ├── __init__.py
│       ├── fixtures.py             # Pytest fixtures
│       └── mocks.py                # Mock implementations
│
├── infra/                          # Infrastructure implementations
│   ├── docker/                     # Docker management (tier 1 impl)
│   ├── rcon/                       # RCON client (tier 3 impl)
│   ├── execution/                  # Execution environments (tier 3 impl)
│   ├── session/                    # Session management
│   └── output/                     # Output utilities
│
├── agent/                          # Domain modules (tier 4 impl)
│   ├── core/                       # Agent identity and lifecycle
│   │   ├── registry.py            # AgentRegistry (Tier 3 service)
│   │   └── profile.py             # AgentProfile (domain model)
│   ├── remote_view.py
│   ├── reachable_view.py
│   ├── embodied_actions/
│   └── ...
│
├── llm/                            # LLM layer (tier 5-6 impl)
│   ├── client/
│   ├── orchestrator.py
│   ├── prompts/
│   └── ...
│
├── cli.py                          # CLI (CONSUMER of Environment)
│
└── views/                          # UI views (CONSUMERS of Environment)
    └── nicegui/
```

**Key distinction**: `environment/tiers/` contains orchestration code that *uses* implementations from `infra/`, `agent/`, `llm/`. The tiers don't re-implement — they coordinate.

---

## Open Questions

1. **Should tier 1 manage Docker lifecycle?**
   - Currently CLI manages Docker — should Environment orchestrate it?
   - Answer: Yes, tier 1 orchestrates Docker (via `infra/docker/`)

2. **How do we handle multi-agent scenarios?**
   - ✅ **Answer**: Multi-agent support is implemented through persistent agent identity:
     - **AgentRegistry** (Tier 3): Manages persistent `AgentProfile` storage
     - **Agent Reconciliation** (Tier 4): Reconciles agent name with persistent profile
     - **Agent Lifecycle**: Supports "New Agent (Spawn)" and "Resume Agent (Bind)" patterns
   - Multiple `Environment` instances can share Tier 1-3 infrastructure
   - Each agent gets its own `Environment` instance (Tier 4-6) with unique `agent_id`
   - Agent profiles persist across sessions, enabling agent continuity
   - See "Agent Lifecycle and Persistence" section for details

3. **Should tier 5 be merged into tier 6?**
   - Prompts are tightly coupled to orchestration
   - But tasks might be separate from prompts

4. **How granular should reset be within a tier?**
   - Reset all of tier 4 vs just reload one module?

5. **What's the persistence story?**
   - ✅ **Agent Persistence**: Implemented via `AgentRegistry` and `AgentProfile`
     - Agent profiles stored in `.fv-output/agents/` (JSON files)
     - Profiles track agent identity, status, stats, and metadata
     - Agents can be resumed across sessions using persistent profiles
   - Environment config saved/loaded from file? (Future work)
   - Session recovery after crash? (Future work)

6. **How do views subscribe to Environment events?**
   - Callback registration?
   - Event bus?

---

## Agent Lifecycle and Persistence

### Overview

The Environment module supports **persistent agent identity** through the `AgentRegistry` and `AgentProfile` system. This enables agents to maintain their identity, configuration, and progress across multiple sessions.

### Components

**AgentRegistry** (Tier 3):
- Located in `src/FactoryVerse/agent/core/registry.py`
- Manages persistent storage of `AgentProfile` objects
- Storage location: `.fv-output/agents/` (JSON files, one per agent)
- Provides: `register()`, `get()`, `get_by_name()`, `list_agents()`, `save()`, `delete()`

**AgentProfile** (Domain Model):
- Located in `src/FactoryVerse/agent/core/profile.py`
- Persistent agent identity with UUID
- Tracks: name, instance_id, model, status, stats, metadata
- Status lifecycle: `CREATED` → `ACTIVE` → `IDLE` → `PAUSED` → `ARCHIVED`

### Agent Reconciliation Strategy

When Tier 4 initializes, it reconciles the requested `agent_id` with persistent profiles:

**Case 1: New Agent (Spawn)**
- Profile: None
- Lua Entity: None
- **Action**: 
  1. Create new `AgentProfile` with UUID
  2. Register profile in `AgentRegistry`
  3. Create Lua entity in Factorio (`destroy_existing=True`)
  4. Set status to `ACTIVE`

**Case 2: Resume Agent (Bind)**
- Profile: Exists
- Lua Entity: Exists (or can be recreated)
- **Action**:
  1. Load existing `AgentProfile` from registry
  2. Bind to existing Lua entity (`destroy_existing=False`)
  3. Update profile status to `ACTIVE`
  4. Use profile's persistent ID and metadata

**Case 3: Legacy Fallback**
- If `AgentRegistry` not available in Tier 3
- Falls back to legacy creation (ephemeral, no persistence)

### Implementation Details

**Tier 3 Initialization**:
```python
# In tier3_python.py
async def _init_agent_registry(self) -> None:
    registry_dir = infra_config.fv_output_dir / "agents"
    self._agent_registry = AgentRegistry(storage_dir=registry_dir)
```

**Tier 4 Agent Creation**:
```python
# In tier4_runtime.py
async def _reconcile_and_create_agent(self) -> None:
    registry = tier3.agent_registry
    requested_id = self.config.agent_id or "agent_1"
    profile = registry.get_by_name(requested_id)
    
    if not profile:
        # Case 1: New Agent
        profile = AgentProfile(
            id=uuid4(),
            name=requested_id,
            instance_id=tier3.instance,
            model=self._env.config.tier6.model,
            status=AgentStatus.ACTIVE,
        )
        registry.register(profile)
        rcon_helper._create_agent(udp_port=udp_port, destroy_existing=True)
    else:
        # Case 2: Resume Agent
        profile.status = AgentStatus.ACTIVE
        registry.save(profile)
        rcon_helper._create_agent(udp_port=udp_port, destroy_existing=False)
```

### Multi-Agent Support

Multiple agents can coexist in the same Factorio instance:

1. **Shared Infrastructure**: Multiple `Environment` instances share Tier 1-3
   - Same RCON connection (via Tier 3)
   - Same UDP dispatcher (via Tier 3)
   - Same AgentRegistry (via Tier 3)

2. **Separate Runtime**: Each agent has its own Tier 4-6
   - Unique `agent_id` (from config or auto-generated)
   - Unique `AgentProfile` (persisted in registry)
   - Separate session directories
   - Independent LLM interactions

3. **Example Usage**:
```python
# Create first agent
env1 = Environment(config=EnvironmentConfig(
    tier4=RuntimeConfig(agent_id="agent_1")
))
await env1.initialize(up_to=Tier.RUNTIME)

# Create second agent (shares Tier 1-3, separate Tier 4-6)
env2 = Environment(config=EnvironmentConfig(
    tier3=PythonConfig(instance=env1.tier3.instance),  # Same instance
    tier4=RuntimeConfig(agent_id="agent_2")
))
await env2.initialize(up_to=Tier.RUNTIME)

# Both agents active, each with persistent profile
```

### Future Enhancements

The current implementation provides the foundation for multi-agent scenarios. Future work may include:

- **ResourceManager**: Automatic UDP port allocation and collision detection
- **SharedInfrastructure**: Reference-counted RCON/UDP connections
- **MultiAgentEnvironment**: High-level orchestrator for managing multiple agents
- **Agent Coordination**: Cross-agent communication and task coordination
- **Agent Statistics**: Long-term progress tracking across sessions

See `docs/architecture/MULTI_AGENT_LIFECYCLE_ANALYSIS.md` for detailed analysis of multi-agent requirements.

---

## Summary

The `environment` module is an **orchestrator** that transforms FactoryVerse from a collection of scripts into a **principled, composable system**.

**What Environment does**:
- Orchestrates tiers 1-6: Factorio infra → Settings → Python infra → Runtime → Specification → Interaction
- Enforces contracts between tiers
- Manages lifecycle (start, stop, reset)
- Provides verification at each tier boundary

**What Environment doesn't do**:
- Implement tier functionality (that's in `infra/`, `agent/`, `llm/`)
- Own the view layer (CLI, NiceGUI are consumers)

This enables:
- **Reliable setup**: No more "hope it works" assumptions
- **Intelligent tooling**: MCP can make smart decisions about resets
- **Easy testing**: Load exactly what you need
- **Clear debugging**: "Which tier failed?" has a clear answer
- **Future extensibility**: New tiers (multi-agent, distributed) fit naturally
- **Clean separation**: Views consume Environment, don't extend it
- **Agent persistence**: Agents maintain identity and progress across sessions

---

## Implementation Status

### ✅ Implemented Features

**Agent Lifecycle and Persistence** (v1.0):
- ✅ `AgentRegistry` service in Tier 3 (`src/FactoryVerse/agent/core/registry.py`)
- ✅ `AgentProfile` domain model (`src/FactoryVerse/agent/core/profile.py`)
- ✅ Agent reconciliation in Tier 4 (`tier4_runtime.py::_reconcile_and_create_agent()`)
- ✅ Persistent storage in `.fv-output/agents/` (JSON files)
- ✅ Support for "New Agent (Spawn)" and "Resume Agent (Bind)" patterns
- ✅ Legacy fallback for environments without registry

**Tier 3 Enhancements**:
- ✅ AgentRegistry initialization (`tier3_python.py::_init_agent_registry()`)
- ✅ Registry accessible via `tier3.agent_registry` property

**Tier 4 Enhancements**:
- ✅ Agent reconciliation with persistent profiles
- ✅ Profile-based agent identity management
- ✅ Status tracking (ACTIVE, IDLE, etc.)

### 🔄 Future Enhancements

**Multi-Agent Infrastructure** (Planned):
- ⏳ `ResourceManager`: Automatic UDP port allocation and collision detection
- ⏳ `SharedInfrastructure`: Reference-counted RCON/UDP connections
- ⏳ `MultiAgentEnvironment`: High-level orchestrator for multiple agents
- ⏳ Cross-agent coordination and communication

**Persistence Enhancements** (Planned):
- ⏳ Environment config persistence
- ⏳ Session recovery after crash
- ⏳ Agent statistics aggregation across sessions

See `docs/architecture/MULTI_AGENT_LIFECYCLE_ANALYSIS.md` for detailed analysis and recommendations.
