# Multi-Agent Lifecycle Analysis: Environment Design Gaps

## Executive Summary

The current `ENVIRONMENT_DESIGN.md` document and implementation focus on **single-agent orchestration** through the Environment class. While the design acknowledges multi-agent scenarios in "Open Questions" (line 654-656), it does not address the **infrastructure/orchestration-level requirements** for managing multiple agents within a single Factorio instance.

This analysis identifies critical gaps in:
1. **Agent Registry & Coordination**: No infrastructure-level service for tracking and coordinating multiple agents
2. **Resource Management**: UDP port allocation, agent ID collision detection
3. **Shared Infrastructure Lifecycle**: Multiple Environment instances sharing Tier 1-3
4. **Agent Lifecycle Coordination**: Starting/stopping agents, handling failures, cleanup

---

## Current State Analysis

### What Environment Currently Provides

The `Environment` class is designed as a **single-agent orchestrator**:

```python
# Current: One Environment = One Agent
env = Environment(config=EnvironmentConfig(
    tier4=RuntimeConfig(agent_id="agent_1")  # Single agent_id
))
await env.initialize(up_to=Tier.RUNTIME)
```

**Key Characteristics:**
- Each `Environment` instance manages one `agent_id` (Tier 4)
- Agent creation happens at Tier 4 initialization (`tier4_runtime.py:148`)
- No coordination between multiple `Environment` instances
- No shared agent registry or lifecycle management

### What's Missing: Infrastructure/Orchestration Layer

The design document mentions multi-agent scenarios but doesn't address:

1. **Agent Registry Service**: A service that tracks all agents in a Factorio instance
2. **Resource Allocation**: UDP port management, agent ID assignment
3. **Lifecycle Coordination**: Starting/stopping multiple agents safely
4. **Shared Tier Management**: Multiple agents sharing Tier 1-3 infrastructure

---

## Gap Analysis

### Gap 1: No Agent Registry at Infrastructure Level

**Current State:**
- Agents are stored in Lua `storage.agents` (game state)
- Python has no centralized registry of active agents
- Each `Environment` instance operates independently

**Problem:**
- Cannot query "what agents are active in this instance?"
- Cannot detect agent ID collisions before creation
- No way to coordinate agent lifecycle across multiple `Environment` instances

**Required:**
```python
class AgentRegistry:
    """Infrastructure-level agent registry.
    
    Tracks all agents in a Factorio instance, manages IDs,
    coordinates lifecycle across multiple Environment instances.
    """
    
    def __init__(self, instance: FactorioInstance):
        self.instance = instance
        self._agents: Dict[str, AgentInfo] = {}  # agent_id -> AgentInfo
    
    async def register_agent(
        self, 
        agent_id: str, 
        environment: Environment,
        udp_port: Optional[int] = None
    ) -> AgentInfo:
        """Register a new agent with the registry."""
        # Check for collisions
        # Allocate UDP port if needed
        # Create agent in Factorio
        # Track in registry
        pass
    
    async def unregister_agent(self, agent_id: str) -> None:
        """Unregister agent and cleanup resources."""
        pass
    
    def list_agents(self) -> List[AgentInfo]:
        """List all registered agents."""
        pass
    
    def get_agent(self, agent_id: str) -> Optional[AgentInfo]:
        """Get agent info by ID."""
        pass
```

**Location in Design:**
- Should be part of **Tier 3 (Python Infra)** or a new **Tier 3.5 (Agent Coordination)**
- Or a separate service that multiple `Environment` instances can access

---

### Gap 2: Resource Management (UDP Ports, Agent IDs)

**Current State:**
- UDP ports are auto-allocated by `UDPDispatcher` (default: 34202)
- Agent IDs are specified in config (`agent_id="agent_1"`)
- No collision detection or port allocation strategy

**Problem:**
- Multiple agents might request the same UDP port
- Agent ID collisions not detected until creation fails
- No strategy for port allocation (sequential, random, etc.)

**Required:**
```python
class ResourceManager:
    """Manages shared resources for multi-agent scenarios."""
    
    def __init__(self, instance: FactorioInstance):
        self.instance = instance
        self._allocated_ports: Set[int] = set()
        self._allocated_agent_ids: Set[str] = set()
    
    async def allocate_udp_port(
        self, 
        preferred: Optional[int] = None
    ) -> int:
        """Allocate a UDP port for an agent.
        
        Args:
            preferred: Preferred port (None for auto-allocation)
            
        Returns:
            Allocated port number
            
        Raises:
            ResourceExhaustedError: If no ports available
        """
        pass
    
    def release_udp_port(self, port: int) -> None:
        """Release a UDP port."""
        pass
    
    async def allocate_agent_id(
        self,
        preferred: Optional[str] = None
    ) -> str:
        """Allocate an agent ID.
        
        Args:
            preferred: Preferred ID (None for auto-generation)
            
        Returns:
            Allocated agent ID
            
        Raises:
            AgentIDCollisionError: If preferred ID already in use
        """
        pass
    
    def release_agent_id(self, agent_id: str) -> None:
        """Release an agent ID."""
        pass
```

**Location in Design:**
- Should be part of **Tier 3 (Python Infra)** or shared service
- Accessed by `Environment` instances when creating agents

---

### Gap 3: Shared Infrastructure Lifecycle

**Current State:**
- Each `Environment` instance manages its own Tier 1-3
- No concept of "shared infrastructure" for multiple agents

**Problem:**
- Multiple `Environment` instances might create duplicate Tier 1-3 connections
- No way to share RCON/UDP connections across agents
- Inefficient resource usage

**Required:**
```python
class SharedInfrastructure:
    """Manages shared Tier 1-3 infrastructure for multiple agents.
    
    Multiple Environment instances can share:
    - Tier 1: Factorio instance (already shared by design)
    - Tier 2: Game settings (shared by design)
    - Tier 3: RCON connection, UDP dispatcher (should be shared)
    """
    
    def __init__(self, instance: FactorioInstance):
        self.instance = instance
        self._rcon: Optional[RCONClient] = None
        self._udp_dispatcher: Optional[UDPDispatcher] = None
        self._ref_count: int = 0  # Reference counting
    
    async def acquire(self) -> SharedInfrastructureHandle:
        """Acquire shared infrastructure.
        
        Returns:
            Handle with rcon, udp_dispatcher
            
        Note:
            First caller initializes, subsequent callers reuse.
        """
        pass
    
    async def release(self) -> None:
        """Release shared infrastructure.
        
        Note:
            Last caller shuts down, others continue using.
        """
        pass
```

**Location in Design:**
- Should be a new concept: **Shared Infrastructure Pool**
- `Environment` instances can opt-in to shared infrastructure
- Or a separate `MultiAgentEnvironment` class that manages this

---

### Gap 4: Agent Lifecycle Coordination

**Current State:**
- Agent lifecycle (create, reset, destroy) is handled at Tier 4
- No coordination between agents
- No cleanup on agent failure

**Problem:**
- If one agent crashes, others aren't notified
- No way to gracefully shutdown all agents
- Agent destruction doesn't coordinate with registry

**Required:**
```python
class AgentLifecycleManager:
    """Coordinates agent lifecycle across multiple Environment instances."""
    
    async def create_agent(
        self,
        environment: Environment,
        agent_id: Optional[str] = None,
        udp_port: Optional[int] = None
    ) -> AgentInfo:
        """Create agent with coordination.
        
        - Registers with AgentRegistry
        - Allocates resources via ResourceManager
        - Creates agent in Factorio
        - Tracks lifecycle state
        """
        pass
    
    async def destroy_agent(
        self,
        agent_id: str,
        cleanup: bool = True
    ) -> None:
        """Destroy agent with coordination.
        
        - Unregisters from AgentRegistry
        - Releases resources
        - Destroys agent in Factorio
        - Notifies other agents (if needed)
        """
        pass
    
    async def reset_agent(self, agent_id: str) -> None:
        """Reset agent (preserves registration)."""
        pass
    
    async def shutdown_all(self) -> None:
        """Gracefully shutdown all agents."""
        pass
```

**Location in Design:**
- Should be part of **Tier 3 (Python Infra)** or separate service
- Accessed by `Environment` instances

---

## Proposed Architecture Changes

### Option A: Extend Environment with Multi-Agent Support

Add multi-agent capabilities directly to `Environment`:

```python
class Environment:
    """Single-agent orchestrator (current design)."""
    
    # ... existing code ...
    
    @classmethod
    def for_multi_agent(
        cls,
        instance: FactorioInstance,
        agent_id: str,
        shared_infra: Optional[SharedInfrastructure] = None
    ) -> "Environment":
        """Create environment for multi-agent scenario.
        
        Args:
            instance: Factorio instance (shared across agents)
            agent_id: This agent's ID
            shared_infra: Optional shared infrastructure pool
        """
        # Use shared infrastructure if provided
        # Register with AgentRegistry
        # Allocate resources via ResourceManager
        pass
```

**Pros:**
- Minimal changes to existing design
- Backward compatible (single-agent still works)

**Cons:**
- `Environment` becomes more complex
- Multi-agent coordination logic mixed with orchestration

---

### Option B: New MultiAgentOrchestrator Layer

Create a new orchestration layer above `Environment`:

```python
class MultiAgentOrchestrator:
    """Orchestrates multiple agents in a single Factorio instance.
    
    Manages:
    - Shared infrastructure (Tier 1-3)
    - Agent registry and lifecycle
    - Resource allocation
    - Coordination between agents
    """
    
    def __init__(self, instance: FactorioInstance):
        self.instance = instance
        self._shared_infra = SharedInfrastructure(instance)
        self._agent_registry = AgentRegistry(instance)
        self._resource_manager = ResourceManager(instance)
        self._lifecycle_manager = AgentLifecycleManager(
            registry=self._agent_registry,
            resource_manager=self._resource_manager
        )
        self._environments: Dict[str, Environment] = {}
    
    async def create_agent_environment(
        self,
        agent_id: Optional[str] = None,
        config: Optional[EnvironmentConfig] = None
    ) -> Environment:
        """Create a new agent environment.
        
        Returns:
            Environment instance for the agent
        """
        # Allocate agent_id if not provided
        # Allocate UDP port
        # Acquire shared infrastructure
        # Create Environment with shared infra
        # Register agent
        # Store in _environments
        pass
    
    async def destroy_agent_environment(
        self,
        agent_id: str
    ) -> None:
        """Destroy an agent environment."""
        # Unregister agent
        # Release resources
        # Shutdown Environment
        # Release shared infrastructure (if last agent)
        pass
    
    def list_agents(self) -> List[AgentInfo]:
        """List all active agents."""
        return self._agent_registry.list_agents()
```

**Pros:**
- Clear separation of concerns
- `Environment` remains single-agent focused
- Multi-agent logic isolated

**Cons:**
- New abstraction layer
- More complex API

---

### Option C: Hybrid Approach (Recommended)

Extend `Environment` with optional multi-agent support, but add infrastructure services:

```python
# Infrastructure services (Tier 3.5 or separate module)
class AgentRegistry: ...
class ResourceManager: ...
class SharedInfrastructure: ...

# Environment remains single-agent, but can use shared services
class Environment:
    def __init__(
        self,
        config: Optional[EnvironmentConfig] = None,
        shared_infra: Optional[SharedInfrastructure] = None,
        agent_registry: Optional[AgentRegistry] = None
    ):
        """Initialize Environment.
        
        Args:
            config: Environment configuration
            shared_infra: Optional shared infrastructure (for multi-agent)
            agent_registry: Optional agent registry (for multi-agent)
        """
        # Use shared_infra if provided, otherwise create own
        # Register with agent_registry if provided
        pass

# New orchestrator for multi-agent scenarios
class MultiAgentEnvironment:
    """Orchestrates multiple agents using shared infrastructure."""
    
    def __init__(self, instance: FactorioInstance):
        self.instance = instance
        self._shared_infra = SharedInfrastructure(instance)
        self._agent_registry = AgentRegistry(instance)
        self._resource_manager = ResourceManager(instance)
        self._environments: Dict[str, Environment] = {}
    
    async def add_agent(
        self,
        agent_id: Optional[str] = None,
        config: Optional[EnvironmentConfig] = None
    ) -> Environment:
        """Add a new agent to the multi-agent environment."""
        # Allocate resources
        # Create Environment with shared infra
        # Register agent
        pass
```

**Pros:**
- `Environment` can work standalone (single-agent) or with shared services (multi-agent)
- Clear infrastructure services
- Flexible usage patterns

**Cons:**
- More complex initialization

---

## Required Design Document Updates

### 1. Add "Tier 3.5: Agent Coordination" (or extend Tier 3)

**New Section:**
```
### Tier 3.5: Agent Coordination (Multi-Agent Support)

**What it is**: Infrastructure-level services for managing multiple agents.

**Components**:
- `AgentRegistry`: Tracks all agents in a Factorio instance
- `ResourceManager`: Allocates UDP ports and agent IDs
- `SharedInfrastructure`: Manages shared RCON/UDP connections
- `AgentLifecycleManager`: Coordinates agent creation/destruction

**Contract**:
- Factorio is running with game loaded (Tier 2 complete)
- RCON connection available (Tier 3 complete)
- Services can query/register agents

**Verification**:
```python
tier3_5.is_ready() -> Tier35Status:
    - registry_initialized: bool
    - resource_manager_ready: bool
    - active_agents: List[str]
```

**Lifecycle**:
- `initialize()`: Initialize services
- `register_agent(env, agent_id)`: Register agent
- `unregister_agent(agent_id)`: Unregister agent
- `list_agents()`: List all agents
```

### 2. Update "Open Questions" Section

**Current (line 654-656):**
```
2. **How do we handle multi-agent scenarios?**
   - Multiple tier 4 instances connected to same tier 1-3?
   - Separate environments per agent?
```

**Updated:**
```
2. **How do we handle multi-agent scenarios?**
   - ✅ Answer: Multi-agent requires infrastructure-level services:
     - AgentRegistry for tracking agents
     - ResourceManager for UDP port/ID allocation
     - SharedInfrastructure for shared Tier 1-3 connections
     - MultiAgentEnvironment orchestrator (or extend Environment)
   - Multiple Environment instances can share Tier 1-3 via SharedInfrastructure
   - Each agent gets its own Environment instance (Tier 4-6)
```

### 3. Add Multi-Agent Use Case

**New Section:**
```
## Multi-Agent Use Cases

### Use Case: Multiple Agents in Same Instance

```python
# Option 1: Using MultiAgentEnvironment
orchestrator = MultiAgentEnvironment(instance=instance)
await orchestrator.initialize_shared_infra()

agent1_env = await orchestrator.add_agent(agent_id="agent_1")
agent2_env = await orchestrator.add_agent(agent_id="agent_2")

await agent1_env.initialize(up_to=Tier.INTERACTION)
await agent2_env.initialize(up_to=Tier.INTERACTION)

# Both agents share Tier 1-3, have separate Tier 4-6

# Option 2: Using shared services directly
shared_infra = SharedInfrastructure(instance)
registry = AgentRegistry(instance)
resource_mgr = ResourceManager(instance)

env1 = Environment(
    config=config1,
    shared_infra=shared_infra,
    agent_registry=registry
)
env2 = Environment(
    config=config2,
    shared_infra=shared_infra,
    agent_registry=registry
)
```

### Use Case: Agent Lifecycle Management

```python
# List all agents
agents = orchestrator.list_agents()
# [AgentInfo(agent_id="agent_1", ...), AgentInfo(agent_id="agent_2", ...)]

# Gracefully shutdown all agents
await orchestrator.shutdown_all()

# Remove specific agent
await orchestrator.remove_agent("agent_1")
```
```

---

## Implementation Recommendations

### Phase 1: Infrastructure Services (Tier 3.5)

1. **Create `AgentRegistry` service**
   - Query agents from Factorio Lua state
   - Track agent metadata (ID, UDP port, Environment reference)
   - Provide list/get/register/unregister methods

2. **Create `ResourceManager` service**
   - UDP port allocation (sequential or configurable range)
   - Agent ID allocation (auto-generate or validate)
   - Collision detection

3. **Create `SharedInfrastructure` service**
   - Reference-counted RCON/UDP connections
   - Acquire/release pattern

### Phase 2: Update Environment

1. **Extend `Environment.__init__`**
   - Accept optional `shared_infra` and `agent_registry` parameters
   - Use shared services if provided, otherwise create own

2. **Update `Tier4Runtime`**
   - Use `ResourceManager` for UDP port allocation
   - Register with `AgentRegistry` on agent creation
   - Unregister on shutdown

### Phase 3: Multi-Agent Orchestrator

1. **Create `MultiAgentEnvironment` class**
   - Manages shared infrastructure
   - Coordinates multiple `Environment` instances
   - Provides high-level multi-agent API

2. **Update documentation**
   - Add multi-agent use cases
   - Document infrastructure services
   - Provide examples

---

## Summary

The current `ENVIRONMENT_DESIGN.md` document and implementation are **single-agent focused** and do not address the infrastructure/orchestration requirements for multi-agent scenarios. Key gaps:

1. **No Agent Registry**: Cannot track/coordinate multiple agents
2. **No Resource Management**: UDP ports and agent IDs not managed
3. **No Shared Infrastructure**: Each Environment creates its own Tier 1-3
4. **No Lifecycle Coordination**: Agents operate independently

**Recommended Solution:**
- Add infrastructure services (AgentRegistry, ResourceManager, SharedInfrastructure)
- Extend Environment to optionally use shared services
- Create MultiAgentEnvironment orchestrator for high-level multi-agent scenarios
- Update design document with Tier 3.5 and multi-agent use cases

This maintains backward compatibility (single-agent still works) while enabling multi-agent scenarios with proper infrastructure-level coordination.
