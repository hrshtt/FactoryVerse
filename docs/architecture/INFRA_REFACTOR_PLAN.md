# Infrastructure Refactor: Unified Execution Layer

## Executive Summary

This document outlines the refactoring of FactoryVerse's infrastructure layer to:
1. **Unify execution environments** (Jupyter vs in-process)
2. **Consolidate entry points** (CLI, MCP, run_agent)
3. **Internalize key utilities** (docs generation, system prompts)
4. **Define clear ownership** between domain (boilerplate) and infrastructure
5. **Reorganize `infra/llm/`** to separate LLM-specific from generic concerns

---

## Current State Analysis

### Entry Points Today

| Entry Point | Location | Purpose | Uses |
|-------------|----------|---------|------|
| `fv` / `factoryverse` | `cli.py` | Server/client management | Docker, instance detection |
| `fv mcp` | `cli.py` → `mcp_server/` | IDE integration | Direct RCON, subprocess |
| `run_agent.py` | `scripts/` | Agent orchestration | `FactoryVerseRuntime` (Jupyter) |
| `generate_docs.py` | `scripts/` | API docs from introspection | Direct imports |
| `assemble_prompt.py` | `scripts/` | System prompt assembly | File I/O |

### Current `infra/llm/` Module Analysis

```
infra/llm/                         # Problem: Mix of LLM-specific and generic concerns
├── client.py                      # LLM-SPECIFIC: PrimeIntellectClient (hardcoded to one API)
├── agent_orchestrator.py          # LLM-SPECIFIC: Turn loop, tool execution, context management
├── session_manager.py             # GENERIC: File-system session/run directory management
├── trajectory_manager.py          # LLM-SPECIFIC: Action history, compression for context
├── tool_validator.py              # LLM-SPECIFIC: DSL/SQL validation before execution
├── output_compressor.py           # LLM-SPECIFIC: Output compression for context limits
├── factorio_error_parser.py       # GENERIC: Error parsing (useful for any consumer)
├── initial_state_generator.py     # LLM-SPECIFIC: Generates context doc for agents
├── tech_recipe_prompt.py          # LLM-SPECIFIC: Tech/recipe formatting for prompts
├── categorical_references.py      # LLM-SPECIFIC: Categorical lists for prompts
├── console_output.py              # GENERIC: Console formatting (useful for CLI too)
├── boilerplate/                   # GENERIC: Domain loading (should be at infra/ level)
└── boilerplate.py                 # GENERIC: Legacy domain script (should be at infra/ level)
```

### Classification of Current Files

| File | Category | Notes |
|------|----------|-------|
| `client.py` | LLM | Hardcoded to Prime Intellect API, needs abstraction |
| `agent_orchestrator.py` | LLM | Core orchestration, tightly coupled to client |
| `session_manager.py` | **Generic** | Just manages directories, not LLM-specific |
| `trajectory_manager.py` | LLM | Context window management |
| `tool_validator.py` | **Hybrid** | Validation is generic, but tuned for LLM safety |
| `output_compressor.py` | LLM | Explicitly for context limits |
| `factorio_error_parser.py` | **Generic** | Parse Lua errors, useful for any consumer |
| `initial_state_generator.py` | LLM | Generates prompt context |
| `tech_recipe_prompt.py` | LLM | Prompt generation |
| `categorical_references.py` | LLM | Prompt generation |
| `console_output.py` | **Generic** | Just ANSI formatting, useful anywhere |
| `boilerplate/` | **Generic** | Domain loading, NOT LLM-specific |
| `boilerplate.py` | **Generic** | Legacy domain script |

### Problems with Current Design

1. **`infra/llm/` is a grab-bag**: Mixes LLM orchestration with generic utilities
2. **`boilerplate/` is in wrong place**: It's domain loading, not LLM-specific
3. **`client.py` is not pluggable**: Hardcoded to one LLM provider
4. **No contracts defined**: What does the LLM layer need from the rest of the system?
5. **`session_manager.py` naming**: "Session" now means both file directories AND boilerplate contexts

---

## Proposed Module Structure

```
FactoryVerse/
├── cli.py                          # Unified CLI entry point
├── runtime.py                      # AgentRuntime (DOMAIN - unchanged)
│
├── infra/
│   ├── boilerplate/                # MOVED: Domain loading (scopes, context)
│   │   ├── __init__.py             # Scope, load(), BoilerplateContext
│   │   ├── rcon.py
│   │   ├── snapshot.py
│   │   ├── agent.py
│   │   ├── runtime.py
│   │   └── test_ground.py
│   │
│   ├── execution/                  # NEW: Unified execution layer
│   │   ├── __init__.py
│   │   ├── base.py                 # ExecutionEnvironment ABC
│   │   ├── jupyter.py              # JupyterExecutor
│   │   └── inprocess.py            # InProcessExecutor
│   │
│   ├── session/                    # NEW: Unified session management
│   │   ├── __init__.py
│   │   ├── session.py              # FactoryVerseSession (executor + context)
│   │   └── file_manager.py         # Directory/file management (from session_manager.py)
│   │
│   ├── output/                     # EXTRACTED: Generic output utilities
│   │   ├── __init__.py
│   │   ├── console.py              # ConsoleOutput (from console_output.py)
│   │   └── error_parser.py         # FactorioErrorParser (from factorio_error_parser.py)
│   │
│   ├── docker/                     # UNCHANGED
│   └── ...
│
├── llm/                            # RENAMED: LLM-specific orchestration layer
│   ├── __init__.py
│   ├── client/                     # LLM client abstraction
│   │   ├── __init__.py
│   │   ├── base.py                 # LLMClient ABC
│   │   ├── openai_compatible.py    # OpenAI-compatible client (most providers)
│   │   └── anthropic.py            # Anthropic-specific (if needed)
│   │
│   ├── orchestrator.py             # FactorioAgentOrchestrator
│   ├── trajectory.py               # TrajectoryManager
│   ├── context/                    # Context management for LLMs
│   │   ├── __init__.py
│   │   ├── compressor.py           # OutputCompressor
│   │   ├── validator.py            # ToolValidator
│   │   └── initial_state.py        # InitialStateGenerator
│   │
│   └── prompts/                    # CONSOLIDATED: All prompt-related generation
│       ├── __init__.py
│       ├── system_prompt.py        # System prompt assembly
│       ├── api_reference.py        # API docs generation (from generate_docs.py)
│       ├── schema_reference.py     # Schema docs (from generate_schema_docs.py)
│       ├── tech_recipes.py         # TechRecipePromptGenerator
│       └── categorical.py          # CategoricalReferenceGenerator
│
├── mcp_server/                     # UPDATED: Uses new session layer
│   ├── __init__.py
│   └── server.py
│
└── # NO tools/ MODULE - CLI absorbs entry points
```

---

## Contract Definitions

### 1. Domain Layer Contract (boilerplate → rest of system)

```python
# infra/boilerplate/__init__.py

class BoilerplateContext:
    """Domain context loaded at a specific scope."""
    
    # Core accessors (always available based on scope)
    @property
    def rcon(self) -> RCONClient: ...
    
    @property
    def database(self) -> Optional[SnapshotDatabase]: ...
    
    @property
    def runtime(self) -> Optional[AgentRuntime]: ...
    
    # Lifecycle
    async def start(self) -> None: ...
    async def stop(self) -> None: ...

# The domain layer provides:
# - RCON connection to Factorio
# - Snapshot database (DuckDB)
# - Agent runtime with affordances
# 
# The domain layer does NOT know about:
# - LLMs, prompts, or context management
# - Jupyter or execution environments
# - Sessions or orchestration
```

### 2. Execution Layer Contract (execution → session)

```python
# infra/execution/base.py

class ExecutionEnvironment(ABC):
    """Abstract execution environment."""
    
    @abstractmethod
    def execute(self, code: str, **kwargs) -> str:
        """Execute code and return result."""
        pass
    
    @abstractmethod
    async def start(self) -> None: ...
    
    @abstractmethod
    async def stop(self) -> None: ...
    
    @abstractmethod
    def inject_globals(self, globals_dict: Dict[str, Any]) -> None:
        """Inject variables into execution namespace."""
        pass

# The execution layer provides:
# - Code execution (sync/async)
# - Namespace management
# - Error capture
#
# The execution layer does NOT know about:
# - Factorio, domain objects, boilerplate
# - LLMs or orchestration
```

### 3. Session Layer Contract (session → orchestrator/MCP)

```python
# infra/session/session.py

class FactoryVerseSession:
    """Complete session combining execution + domain."""
    
    def __init__(
        self,
        session_id: str,
        executor: ExecutionEnvironment,
        scope: Scope = Scope.RUNTIME,
        **boilerplate_kwargs
    ): ...
    
    @property
    def context(self) -> BoilerplateContext: ...
    
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    
    def execute(self, code: str) -> str: ...
    
    def get_tool_definitions(self) -> List[Dict]: ...

# The session layer provides:
# - Combined execution + domain
# - Tool definitions for orchestrators
# - Lifecycle management
#
# The session layer does NOT know about:
# - Specific LLM providers
# - User interface (CLI, MCP)
```

### 4. LLM Layer Contract (llm → session)

```python
# llm/client/base.py

class LLMClient(ABC):
    """Abstract LLM client."""
    
    @abstractmethod
    def chat_completion(
        self,
        messages: List[Dict],
        tools: Optional[List[Dict]] = None,
    ) -> ChatMessage: ...

# llm/orchestrator.py

class AgentOrchestrator:
    """LLM-powered agent orchestration."""
    
    def __init__(
        self,
        client: LLMClient,           # Pluggable LLM client
        session: FactoryVerseSession, # Session for execution
        **config
    ): ...
    
    async def run_turn(self, user_message: str) -> str: ...

# The LLM layer provides:
# - Chat completion with tool use
# - Context management (compression, pruning)
# - Trajectory tracking
# - Prompt generation
#
# The LLM layer receives:
# - Session for code execution
# - Tool definitions from session
# - System prompt (generated or provided)
```

---

## LLM Client Abstraction

### Current Problem

```python
# client.py - hardcoded to one provider
class PrimeIntellectClient:
    def __init__(self, api_key: str, base_url: str = "https://api.pinference.ai/api/v1", ...):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
```

### Proposed Abstraction

```python
# llm/client/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Dict, Optional, Any

@dataclass
class ChatMessage:
    """Normalized chat message."""
    role: str
    content: Optional[str]
    tool_calls: Optional[List[Dict]] = None

class LLMClient(ABC):
    """Abstract LLM client with OpenAI-compatible interface."""
    
    @abstractmethod
    def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.1,
    ) -> ChatMessage:
        """Execute chat completion with optional tool use."""
        pass
    
    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the model identifier."""
        pass

# llm/client/openai_compatible.py
class OpenAICompatibleClient(LLMClient):
    """Client for OpenAI-compatible APIs."""
    
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: Optional[str] = None,  # None = OpenAI default
        default_headers: Optional[Dict[str, str]] = None,
    ):
        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            default_headers=default_headers,
        )
        self._model = model
    
    def chat_completion(self, messages, tools=None, temperature=0.1):
        # ... implementation
    
    @property
    def model_name(self) -> str:
        return self._model

# Factory functions for common providers
def create_openai_client(api_key: str, model: str = "gpt-4o") -> LLMClient:
    return OpenAICompatibleClient(api_key=api_key, model=model)

def create_anthropic_client(api_key: str, model: str = "claude-sonnet-4-20250514") -> LLMClient:
    # Anthropic uses different SDK
    return AnthropicClient(api_key=api_key, model=model)

def create_prime_intellect_client(api_key: str, model: str = "intellect-3") -> LLMClient:
    return OpenAICompatibleClient(
        api_key=api_key,
        model=model,
        base_url="https://api.pinference.ai/api/v1",
    )
```

## Core Abstractions

#### 1. ExecutionEnvironment (ABC)

```python
# infra/execution/base.py
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

class ExecutionEnvironment(ABC):
    """Abstract base for code execution environments."""
    
    @abstractmethod
    def execute(self, code: str, **kwargs) -> str:
        """Execute code and return result."""
        pass
    
    @abstractmethod
    async def start(self) -> None:
        """Start the execution environment."""
        pass
    
    @abstractmethod
    async def stop(self) -> None:
        """Stop and cleanup."""
        pass
    
    @abstractmethod
    def is_running(self) -> bool:
        """Check if environment is running."""
        pass
```

#### 2. JupyterExecutor

```python
# infra/execution/jupyter.py
class JupyterExecutor(ExecutionEnvironment):
    """Jupyter kernel execution (for full agent runs)."""
    
    def __init__(self, notebook_path: Path, kernel_name: str = "fv"):
        self.km = KernelManager(kernel_name=kernel_name)
        # ... existing FactoryVerseRuntime logic
    
    def execute(self, code: str, **kwargs) -> str:
        # Existing execute_code logic
        pass
```

#### 3. InProcessExecutor

```python
# infra/execution/inprocess.py
class InProcessExecutor(ExecutionEnvironment):
    """In-process execution (for MCP, testing)."""
    
    def __init__(self):
        self._globals: Dict[str, Any] = {}
        self._started = False
    
    def execute(self, code: str, **kwargs) -> str:
        exec(code, self._globals)
        return self._globals.get("__result__", "")
    
    async def start(self) -> None:
        self._started = True
    
    async def stop(self) -> None:
        self._globals.clear()
        self._started = False
```

#### 4. FactoryVerseSession

```python
# infra/session/session.py
from FactoryVerse.infra.llm.boilerplate import load, Scope, BoilerplateContext
from FactoryVerse.infra.execution import ExecutionEnvironment

class FactoryVerseSession:
    """Unified session combining execution environment + domain context."""
    
    def __init__(
        self,
        session_id: str,
        executor: ExecutionEnvironment,
        scope: Scope = Scope.RUNTIME,
        **boilerplate_kwargs
    ):
        self.session_id = session_id
        self.executor = executor
        self.scope = scope
        self._ctx: Optional[BoilerplateContext] = None
        self._boilerplate_kwargs = boilerplate_kwargs
    
    @property
    def context(self) -> BoilerplateContext:
        """Lazy-load boilerplate context."""
        if self._ctx is None:
            self._ctx = load(scope=self.scope, **self._boilerplate_kwargs)
        return self._ctx
    
    async def start(self) -> None:
        """Start executor and domain context."""
        await self.executor.start()
        
        if isinstance(self.executor, JupyterExecutor):
            # Load boilerplate into Jupyter kernel
            self.executor.execute(get_runtime_script())
        else:
            # Start domain context directly
            await self.context.start()
    
    def execute(self, code: str, **kwargs) -> str:
        """Execute code in session context."""
        return self.executor.execute(code, **kwargs)
    
    async def stop(self) -> None:
        await self.executor.stop()
        if self._ctx is not None:
            await self._ctx.stop()
```

---

## Entry Point Consolidation

### CLI Commands (Updated pyproject.toml)

```toml
[project.scripts]
# Core CLI - the single entry point
factoryverse = "FactoryVerse.cli:main"
fv = "FactoryVerse.cli:main"

# MCP Server - separate for IDE integration config
factoryverse-mcp = "FactoryVerse.mcp_server:main"

# Agent runner - separate for direct invocation
factoryverse-agent = "FactoryVerse.llm.orchestrator:main"
```

All other functionality moves into CLI subcommands, keeping the entry point surface small.

### CLI Subcommands (Extended cli.py)

The CLI is already scoped for **setup** operations. Adding LLM-related setup commands:

```python
# In cli.py - new subcommands

# ========== PROMPTS COMMAND ==========
prompts_parser = subparsers.add_parser("prompts", help="LLM prompt generation")
prompts_subparsers = prompts_parser.add_subparsers(dest="prompts_action")

# fv prompts generate - generate full system prompt
prompts_generate = prompts_subparsers.add_parser("generate", help="Generate system prompt")
prompts_generate.add_argument("-o", "--output", help="Output path", default="system_prompt.md")
prompts_generate.add_argument("--include-api", action="store_true", help="Include API reference")
prompts_generate.add_argument("--include-schema", action="store_true", help="Include schema docs")
prompts_generate.set_defaults(func=cmd_prompts_generate)

# fv prompts api - generate only API reference
prompts_api = prompts_subparsers.add_parser("api", help="Generate API reference only")
prompts_api.add_argument("-o", "--output", default="docs/reference/api_reference.md")
prompts_api.set_defaults(func=cmd_prompts_api)

# fv prompts schema - generate only schema reference
prompts_schema = prompts_subparsers.add_parser("schema", help="Generate schema reference only")
prompts_schema.add_argument("-o", "--output", default="docs/reference/schema_reference.md")
prompts_schema.set_defaults(func=cmd_prompts_schema)

# ========== AGENT COMMAND ==========
agent_parser = subparsers.add_parser("agent", help="Run LLM agent")
agent_parser.add_argument("--model", help="LLM model name")
agent_parser.add_argument("--mode", choices=["assisted", "autonomous"], default="assisted")
agent_parser.add_argument("--max-turns", type=int, help="Max turns for autonomous")
agent_parser.set_defaults(func=cmd_agent)
```

### Command Handler Implementations

```python
def cmd_prompts_generate(args):
    """Generate consolidated system prompt."""
    from FactoryVerse.llm.prompts import generate_system_prompt
    
    output_path = Path(args.output)
    prompt = generate_system_prompt(
        include_api_reference=args.include_api,
        include_schema=args.include_schema,
    )
    output_path.write_text(prompt)
    print(f"✅ System prompt generated: {output_path}")

def cmd_prompts_api(args):
    """Generate API reference documentation."""
    from FactoryVerse.llm.prompts.api_reference import generate_api_reference
    
    output_path = Path(args.output)
    docs = generate_api_reference()
    output_path.write_text(docs)
    print(f"✅ API reference generated: {output_path}")

def cmd_prompts_schema(args):
    """Generate schema documentation."""
    from FactoryVerse.llm.prompts.schema_reference import generate_schema_reference
    
    output_path = Path(args.output)
    docs = generate_schema_reference()
    output_path.write_text(docs)
    print(f"✅ Schema reference generated: {output_path}")

def cmd_agent(args):
    """Run LLM agent orchestrator."""
    import asyncio
    from FactoryVerse.llm.orchestrator import run_agent
    
    asyncio.run(run_agent(
        model=args.model,
        mode=args.mode,
        max_turns=args.max_turns,
    ))
```

### Complete CLI Structure

```
fv
├── client                  # Local Factorio client management
│   ├── launch
│   ├── log
│   └── dump-data
├── server                  # Docker server management
│   ├── start
│   ├── stop
│   ├── restart
│   ├── logs
│   └── list-scenarios
├── instance                # Instance detection
│   ├── list
│   └── active
├── data                    # Data dump management
│   ├── prune
│   └── refresh
├── prompts                 # NEW: LLM prompt/docs generation
│   ├── generate            # Full system prompt
│   ├── api                 # API reference only
│   └── schema              # Schema reference only
├── agent                   # NEW: Run LLM agent
└── mcp                     # Start MCP server
```

---

## MCP: Dual Role as Development Tool and Agent Gateway

MCP serves two distinct but complementary purposes:

### Role 1: Development & Debugging Tool

MCP enables IDE-driven development by managing game session lifecycle directly:

| Capability | Description | Tools |
|------------|-------------|-------|
| **Session Management** | Create/destroy game sessions from IDE | `create_session`, `destroy_session` |
| **Live Code Execution** | Test Python code against live game | `execute_in_session` |
| **State Inspection** | Query game state via DuckDB | `execute_duckdb` |
| **Hot Reload** | Reload Python/Lua without restart | `reload_session` |
| **Multi-Agent Testing** | Run multiple agents in parallel | Multiple sessions |

This offloads the "inner loop" of development:
- Write code in IDE → Test via MCP → See results → Iterate
- No need to restart `run_agent.py` for every change
- Debug RCON commands, query results, agent behavior interactively

### Role 2: Standalone Agent Execution

MCP can replicate `factoryverse-agent`'s functionality independently:

```
┌─────────────────────────────────────────────────────────────────┐
│                   EQUIVALENT EXECUTION PATHS                     │
├─────────────────────────────────────────────────────────────────┤
│  factoryverse-agent              │  MCP (via IDE/Claude)        │
│  ─────────────────               │  ─────────────────           │
│  1. Create Jupyter kernel        │  1. create_session           │
│  2. Load boilerplate             │     (loads boilerplate)      │
│  3. Generate system prompt       │  2. generate_prompt (tool)   │
│  4. Run agent loop               │  3. Execute code repeatedly  │
│  5. Execute tool calls           │     (execute_in_session)     │
│  6. Log to notebook              │  4. Session state persists   │
└─────────────────────────────────────────────────────────────────┘
```

This means an IDE with MCP tools can:
- Create a session, load full RUNTIME scope
- Execute arbitrary agent actions
- Be the "agent" itself (human-in-the-loop or Claude-in-IDE)

### MCP Tool Categories

```
MCP Tools
├── Session Lifecycle           # Role 1 & 2
│   ├── create_session          # Start new game session
│   ├── destroy_session         # Cleanup session
│   ├── reload_session          # Hot-reload boilerplate
│   └── list_sessions           # Show active sessions
│
├── Code Execution              # Role 1 & 2
│   ├── execute_in_session      # Run Python in session context
│   └── execute_duckdb          # Run SQL queries
│
├── Development Utilities       # Role 1 (dev-focused)
│   ├── run_test                # Run specific test file
│   ├── regenerate_docs         # Rebuild API reference
│   └── validate_code           # Check code before execution
│
└── Agent Capabilities          # Role 2 (agent-focused)
    ├── get_system_prompt       # Fetch current system prompt
    ├── get_initial_state       # Generate state summary
    └── get_tool_definitions    # Export tool schemas
```

### Implementation

```python
# mcp_server/server.py

class FactoryVerseMCPServer:
    def __init__(self):
        self._sessions: Dict[str, FactoryVerseSession] = {}
    
    async def _create_session(self, args: dict) -> list[TextContent]:
        from FactoryVerse.infra.session import FactoryVerseSession
        from FactoryVerse.infra.execution import InProcessExecutor
        from FactoryVerse.infra.boilerplate import Scope
        
        session_id = args["session_id"]
        scope = Scope(args.get("scope", 3))
        
        # Create in-process executor (no Jupyter overhead for MCP)
        executor = InProcessExecutor()
        
        session = FactoryVerseSession(
            session_id=session_id,
            executor=executor,
            scope=scope,
            instance=args.get("instance"),
            agent_id=args.get("agent_id", "agent_1"),
        )
        
        await session.start()
        self._sessions[session_id] = session
        
        return [TextContent(text=json.dumps({"success": True, ...}))]
    
    async def _execute_in_session(self, args: dict) -> list[TextContent]:
        session = self._sessions.get(args["session_id"])
        if not session:
            return [TextContent(text='{"error": "Session not found"}')]
        
        result = session.execute(args["code"])
        return [TextContent(text=json.dumps({"result": result}))]
```

---

## Migration Path

### Phase 1: Create Execution Layer
1. Create `infra/execution/` with base, jupyter, inprocess modules
2. Refactor `agent_runtime.py` → `infra/execution/jupyter.py`
3. Keep backward compatibility via `agent_runtime.py` importing from new location

### Phase 2: Create Session Layer
1. Create `infra/session/` with unified session management
2. Update `boilerplate/` to integrate with sessions (not own execution)
3. Update MCP to use new session layer

### Phase 3: Consolidate Prompts Module
1. Create `llm/prompts/` with consolidated structure
2. Move `scripts/generate_docs.py` logic → `llm/prompts/api_reference.py`
3. Move `scripts/generate_schema_docs.py` logic → `llm/prompts/schema_reference.py`
4. Move `scripts/assemble_prompt.py` logic → `llm/prompts/system_prompt.py`
5. Keep scripts as thin wrappers for backward compatibility (if needed)

### Phase 4: Extend CLI
1. Add `fv prompts` subcommand with generate/api/schema
2. Add `fv agent` subcommand wrapping `run_agent.py` logic
3. Update `pyproject.toml` to remove standalone scripts
4. Update documentation

---

## Design Principles

1. **Boilerplate = Domain Only**
   - `boilerplate/` module knows about RCON, snapshots, agents, runtime
   - Does NOT know about Jupyter, MCP, orchestration

2. **Execution = Infrastructure**
   - `execution/` module handles WHERE code runs
   - JupyterExecutor vs InProcessExecutor

3. **Session = Bridge**
   - `session/` combines execution environment + domain context
   - Single abstraction for run_agent, MCP, tests

4. **Entry Points = User Interfaces**
   - CLI, MCP, scripts are thin wrappers
   - All logic in importable modules

5. **Package-First**
   - Everything importable from package
   - Scripts are convenience wrappers, not core logic

---

## Open Questions

1. **Should MCP use Jupyter?**
   - Pro: Same execution model as run_agent
   - Con: Overhead, complexity for dev tools
   - Recommendation: No, InProcessExecutor is fine for MCP use cases

2. **How to handle async in InProcessExecutor?**
   - Need event loop management
   - Recommendation: InProcessExecutor runs async code via `asyncio.run()`

3. **Session persistence?**
   - Currently sessions are in-memory
   - Could serialize to disk for crash recovery
   - Recommendation: Keep in-memory for v1, add persistence later

4. **Documentation live reload?**
   - MCP could regenerate docs on demand
   - Recommendation: Add `factoryverse_regenerate_docs` MCP tool

---

## Next Steps

1. [ ] Create `infra/execution/` module structure
2. [ ] Implement `ExecutionEnvironment` ABC
3. [ ] Migrate `FactoryVerseRuntime` → `JupyterExecutor`
4. [ ] Create `InProcessExecutor`
5. [ ] Create `FactoryVerseSession` bridge class
6. [ ] Update MCP to use new session layer
7. [ ] Internalize doc/prompt generation
8. [ ] Update pyproject.toml entry points
9. [ ] Migrate run_agent.py logic to package
10. [ ] Write migration guide for existing code
