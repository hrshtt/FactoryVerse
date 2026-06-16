# Domain Agent Lifecycle & Orchestration

## Context
Recent analyses (`MULTI_AGENT_LIFECYCLE_ANALYSIS.md`) identified gaps in *infrastructure* orchestration (registries, resource allocation). However, a larger gap exists at the **Domain Level**: Agents in FactoryVerse are currently **ephemeral**. They are created, run for a session, and then often destroyed or lost.

To treat Agents as first-class domain entities ("Characters" rather than just "Processes"), we need a system that tracks them, couples them with instances, and reasons about their history and evolution.

## The Core Concept: Persistent Agent Identity

We must shift from "Running an Agent Session" to "Resuming an Agent".

### 1. The Agent Profile
An Agent should have a persistent profile independent of any running process or `Environment` instance.

```python
class AgentProfile:
    id: UUID
    name: str
    description: str
    
    # The "Home" instance (World) this agent lives in
    instance_id: str 
    
    # Configuration
    model: str
    mode: InteractionMode
    
    # Persistence
    created_at: datetime
    total_play_time: timedelta
    
    # State
    status: AgentStatus # ACTIVE, PAUSED, ARCHIVED
    current_session_id: Optional[str]
```

### 2. Domain-Level Tracking (Stats & History)
Beyond simple logs (`trajectory.jsonl`), we need aggregated domain statistics.

**The "Stat Sheet" (DuckDB Table):**
*   `total_entities_placed`: count
*   `total_items_crafted`: count
*   `technologies_researched`: list<str>
*   `enemies_killed`: count
*   `deaths`: count
*   `errors_encountered`: count

**The "Journal" (Semantic History):**
Instead of just raw tool calls, we should synthesize "Episodes" or "Achievements".
*   "Established Iron Mining Outpost at (100, 200)"
*   "Defended against biter attack (Wave 5)"

## Proposed Architecture

### A. The Agent Registry (Domain + Infra)
The `AgentRegistry` (proposed in `MULTI_AGENT_LIFECYCLE_ANALYSIS.md`) should be the bridge between Infrastructure and Domain.

*   **Infrastructure Role**: "Is Agent X running? on what port?"
*   **Domain Role**: "Who is Agent X? Where is their data?"

```python
class AgentRegistry:
    # Infrastructure (Volatile)
    _active_processes: Dict[AgentID, ProcessInfo]
    
    # Domain (Persistent)
    _profiles: DB[AgentID, AgentProfile]
    
    def get_profile(self, agent_id: str) -> AgentProfile: ...
    def bind_agent_to_instance(self, agent: AgentProfile, instance: FactorioInstance): ...
```

### B. Entity Reconciliation Strategy
The core challenge is reconciling the **AgentProfile** (Intent) with the **Lua Entity** (Reality).

We define three startup states:

1.  **New Agent (Spawn)**
    *   `Profile`: None
    *   `Lua Entity`: None
    *   **Action**: Create Profile -> Create Lua Entity ( `destroy_existing=True` ) -> Register.

2.  **Resume Agent (Bind)**
    *   `Profile`: Exists
    *   `Lua Entity`: Exists
    *   **Action**: Load Profile -> **Do NOT Destroy** -> Bind RCON/UDP to existing entity -> Update Status to ACTIVE.

3.  **Resurrection (Respawn)**
    *   `Profile`: Exists
    *   `Lua Entity`: None (or Dead/Missing)
    *   **Action**: Load Profile -> Detect Missing Entity -> **Respawn** (Create Lua Entity) -> Log "Resurrection" event.

*Note: "Adoption" (Entity exists, Profile missing) is treated as an error or requires manual intervention to prevent accidental takeover of unknown entities.*

### C. LLM Coupling & Ownership
*   **AgentProfile Owns "Personality"**: The Profile defines the *Default* Model, System Prompt, and "Character" description. This ensures `agent_1` feels like the same agent across sessions.
*   **Session Owns "Intelligence"**: A specific *Session* can override the model (e.g., using a cheaper model for maintenance, or a smarter model for architecture).
*   **Reasoning**: This allows us to upgrade the "Brain" (Model) without destroying the "Person" (Agent).

### D. The "Agent Brain" (State Persistence)
The `AgentSession` currently has a `TrajectoryWriter`. We should elevate this.

*   **Short-term Memory**: The Context Window (managed by `AgentOrchestrator`).
*   **Long-term Memory**: Vector DB (RAG) + DuckDB (World Knowledge).

These must be stored in the **Agent's Home Directory**, not just the "Session Directory".
*   `~/.fv/agents/{agent_id}/memory/` (Vector store)
*   `~/.fv/agents/{agent_id}/profile.json`
*   `~/.fv/agents/{agent_id}/stats.duckdb`

## Implementation Strategy

### Phase 1: The Domain Models
Create `src/FactoryVerse/agent/core/` to house:
*   `profile.py`: `AgentProfile` pydantic model.
*   `stats.py`: `AgentStats` tracker.

### Phase 2: Registry Implementation
Implement `FactoryVerse.infra.services.AgentRegistry` that uses a simple file-based DB (or SQLite) to track profiles.

### Phase 3: Runtime Adaptation
Modify `Tier4Runtime` to:
*   Use `AgentRegistry` to look up agents.
*   Implement the **Reconciliation Logic** (New vs Resume vs Resurrect).
*   Pass `destroy_existing=False` by default when resuming.

### Phase 4: Stats Integration
Hook into `TrajectoryWriter` or `JupyterExecutor` to stream events to `AgentStats`.
