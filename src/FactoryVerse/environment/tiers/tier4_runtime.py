"""Tier 4: FactoryVerse Runtime.

Orchestrates agent modules: remote_view, reachable_view, embodied_actions, DuckDB.

Supports two execution modes:
- JUPYTER: Code runs in isolated Jupyter kernel with notebook logging
- INPROCESS: Code runs in same Python process (lightweight, no notebook)
"""

import asyncio
import logging
import time
from pathlib import Path
from typing import Optional, Any, List, TYPE_CHECKING

from ..config import (
    RuntimeConfig,
    RuntimeVariant,
    RuntimeAccessProfile,
    ExecutionMode,
    SessionMode,
)
from ..status import Tier4Status, TierState, PrerequisiteResult
from .base import TierBase, Tier, TierInitializationError

if TYPE_CHECKING:
    from ..environment import Environment
    from FactoryVerse.infra.execution.base import ExecutionEnvironment
    from FactoryVerse.infra.session.file_manager import SessionConfig
    from FactoryVerse.game.scenarios.base import ScenarioAdapter

logger = logging.getLogger(__name__)


_MAX_ERROR_MESSAGE_CHARS = 500
_MAX_SOURCE_LINE_CHARS = 160


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit] + "…"


def _format_execution_error(
    exc: BaseException,
    code: str,
    exec_filename: str,
    line_offset: int,
) -> str:
    """Say where a code block failed and what it had already done.

    Constitution §8: the model cannot see a traceback and cannot catch this
    exception, so the returned text is the only account it gets of a partial
    execution. Keep it to a few lines — the failing line, the top-level
    statement that reached it, and an explicit statement about what already ran.

    The first line always starts with "Error: " — downstream success detection
    keys on that prefix.
    """
    source_lines = code.split("\n")

    def source(lineno: int) -> str:
        if 1 <= lineno <= len(source_lines):
            return _clip(source_lines[lineno - 1], _MAX_SOURCE_LINE_CHARS)
        return ""

    # SyntaxError's str() appends the internal compile filename; use its own
    # message so the harness does not leak that name into the agent's context.
    message = exc.msg if isinstance(exc, SyntaxError) and exc.msg else exc
    parts = [f"Error: {type(exc).__name__}: {_clip(message, _MAX_ERROR_MESSAGE_CHARS)}"]

    if (
        isinstance(exc, SyntaxError)
        and exc.lineno is not None
        and exc.filename in (exec_filename, None)
    ):
        lineno = exc.lineno - line_offset
        text = _clip(exc.text or source(lineno) or "", _MAX_SOURCE_LINE_CHARS)
        parts.append(f"  line {lineno}: {text}" if text else f"  line {lineno}")
        parts.append("Nothing in this block ran: it did not compile.")
        return "\n".join(parts)

    # Only frames compiled from THIS block carry exec_filename, so line
    # numbers are always read against the source that produced them.
    block_lines = []
    tb = exc.__traceback__
    while tb is not None:
        if tb.tb_frame.f_code.co_filename == exec_filename:
            block_lines.append(tb.tb_lineno - line_offset)
        tb = tb.tb_next

    if not block_lines:
        parts.append(
            "  (raised below this block — inside the agent API, or inside a "
            "helper defined by an earlier block)"
        )
        return "\n".join(parts)

    innermost, outermost = block_lines[-1], block_lines[0]
    parts.append(f"  line {innermost}: {source(innermost)}".rstrip())
    if innermost != outermost:
        parts.append(f"  reached from line {outermost}: {source(outermost)}".rstrip())
    parts.append(
        f"Statements before line {outermost} already ran; their effects on the "
        f"world stand. Statements after it did not run. Variables assigned in "
        f"this block were NOT saved — a block that raises leaves the namespace "
        f"as it was."
    )
    return "\n".join(parts)


class Tier4Runtime(TierBase):
    """Tier 4: FactoryVerse Runtime.

    Loads agent modules for interacting with Factorio:
    - MINIMAL variant: Core modules only (no DuckDB, no remote_view)
    - FULL variant: All modules including remote_view + DuckDB

    Modules loaded:
    - embodied_actions: Walking, mining, crafting, building
    - reachable_view: Lua-based entity querying (always available)
    - remote_view: SQL-based entity querying (FULL only)
    - DuckDB database: Persistent game state (FULL only)
    """

    tier_level = Tier.RUNTIME

    def __init__(self, environment: "Environment"):
        super().__init__(environment)
        self._agent_id: Optional[str] = None
        self._agent_numeric_id: Optional[int] = None
        self._session_dir: Optional[Path] = None
        self._session_config: Optional["SessionConfig"] = None  # Session metadata
        self._snapshot_database: Optional[Any] = None  # SnapshotDatabase wrapper
        self._database: Optional[Any] = None  # Raw DuckDB connection
        self._remote_view: Optional[Any] = None
        self._reachable_view: Optional[Any] = None
        self._entity_reference: Optional[Any] = None
        self._embodied_actions: Optional[Any] = None
        self._modules_loaded: List[str] = []

        # Execution environment (Jupyter or InProcess)
        self._executor: Optional["ExecutionEnvironment"] = None
        self._notebook_path: Optional[Path] = None

        # Scenario adapter (type-safe interface to scenario-specific capabilities)
        self._scenario_adapter: Optional["ScenarioAdapter"] = None

        # EventStream for temporal perception (game events over time)
        self._event_stream: Optional[Any] = None

        # Trajectory writer for mechanistic event logging (source of truth)
        self._trajectory_writer: Optional[Any] = None

        # Persistent user namespace for code execution (survives across blocks)
        self._user_namespace: dict = {}
        # The planning turn's plan helper (TURN_CONTRACT §6); bound by tier 6.
        self._plan_store: Optional[Any] = None

        # Monotonic counter giving each executed block a unique code filename
        self._exec_sequence: int = 0

    @property
    def config(self) -> RuntimeConfig:
        """Get tier 4 configuration."""
        return self._env.config.tier4

    @property
    def agent_id(self) -> Optional[str]:
        """Get agent identifier (the string interface_name, e.g. 'agent_1')."""
        return self._agent_id

    @property
    def agent_numeric_id(self) -> Optional[int]:
        """Get the agent's numeric id (e.g. 1).

        This is the key the Lua ``agent`` interface expects for agent-keyed methods
        (``add_items``, ``clear_inventory``, ``destroy_agents``, ...), whose schema
        declares ``agent_id`` as a number. Distinct from :attr:`agent_id`, which is
        the string ``interface_name`` ('agent_' + this number).
        """
        return self._agent_numeric_id

    @property
    def session_dir(self) -> Optional[Path]:
        """Get session directory."""
        return self._session_dir

    @property
    def chat_log_path(self) -> Optional[Path]:
        """Get chat log path."""
        return self._session_dir / "chat.md" if self._session_dir else None

    @property
    def debug_log_path(self) -> Optional[Path]:
        """Get debug log path."""
        return self._session_dir / "debug.log" if self._session_dir else None

    @property
    def initial_state_path(self) -> Optional[Path]:
        """Get initial state path."""
        return self._session_dir / "initial_state.md" if self._session_dir else None

    @property
    def system_prompt_path(self) -> Optional[Path]:
        """Get system prompt path (ephemeral, session-scoped)."""
        return self._session_dir / "system_prompt.md" if self._session_dir else None

    @property
    def trajectory_path(self) -> Optional[Path]:
        """Get trajectory file path (source of truth for run history)."""
        return self._session_dir / "trajectory.jsonl" if self._session_dir else None

    @property
    def trajectory_writer(self) -> Optional[Any]:
        """Get TrajectoryWriter for event logging.

        The trajectory writer is the source of truth for what happened during
        a run. Both LLM and eval runs use this for mechanistic event logging.

        Tier 4 creates the writer; Tier 6 (if used) adds LLM-specific events.
        """
        return self._trajectory_writer

    @property
    def database(self) -> Optional[Any]:
        """Get DuckDB connection (None if MINIMAL variant)."""
        return self._database

    @property
    def remote_view(self) -> Optional[Any]:
        """Get RemoteView for SQL-based queries (None if MINIMAL variant)."""
        return self._remote_view

    @property
    def reachable_view(self) -> Optional[Any]:
        """Get ReachableView for Lua-based queries."""
        return self._reachable_view

    @property
    def embodied_actions(self) -> Optional[Any]:
        """Get EmbodiedActions for agent actions."""
        return self._embodied_actions

    @property
    def entity_reference(self) -> Optional[Any]:
        """The planning-time reference accessor (Constitution §6)."""
        return self._entity_reference

    @property
    def notebook_path(self) -> Optional[Path]:
        """Get notebook path (only available in JUPYTER mode)."""
        return self._notebook_path

    @property
    def executor(self) -> Optional["ExecutionEnvironment"]:
        """Get the execution environment (JupyterExecutor or InProcessExecutor)."""
        return self._executor

    @property
    def session_config(self) -> Optional["SessionConfig"]:
        """Get session configuration/metadata (for trajectory tracking)."""
        return self._session_config

    @property
    def scenario(self) -> Optional["ScenarioAdapter"]:
        """Get scenario adapter for scenario-specific capabilities.

        Returns the loaded scenario adapter (e.g., LabGridAdapter for lab-grid),
        or None if no scenario adapter was detected/loaded.

        Example:
            >>> if tier4.scenario:
            ...     # Lab-grid specific operations
            ...     result = tier4.scenario.create_agent_in_cell(cell_index=5)
        """
        return self._scenario_adapter

    @property
    def events(self) -> Optional[Any]:
        """Get EventStream for temporal perception of game events.

        The EventStream provides the agent's view of asynchronous game state
        changes - the temporal complement to spatial views (ReachableView, RemoteView).

        Events include:
        - Research completions (unlocks new capabilities)
        - Crafting completions (for fire-and-forget NQ/DQ pattern)
        - Other game state changes

        Example:
            >>> # Drain pending events
            >>> events = await tier4.events.drain()
            >>> for event in events:
            ...     print(f"Event: {event}")
            >>>
            >>> # Wait for specific event
            >>> event = await tier4.events.wait_for(
            ...     "research_finished",
            ...     predicate=lambda e: e.data.get("technology") == "automation"
            ... )
        """
        return self._event_stream

    async def verify_prerequisites(self) -> PrerequisiteResult:
        """Verify Tier 3 (Python Infra) is ready."""
        tier3 = self._env.tier3

        if tier3 is None or not tier3.is_ready:
            return PrerequisiteResult.failed(
                missing=["tier3_python_infra"],
                message="Python infrastructure (RCON/UDP) must be connected first",
            )

        return PrerequisiteResult.ok()

    async def initialize(self) -> None:
        """Initialize runtime with agent modules."""
        self._set_state(TierState.INITIALIZING)

        try:
            # Setup agent and session
            self._agent_id = self.config.agent_id
            self._session_dir = await self._setup_session_dir()

            # Setup trajectory writer (source of truth for run history)
            await self._setup_trajectory_writer()

            # Create execution environment based on config
            await self._setup_executor()

            # Create agent in Factorio
            await self._reconcile_and_create_agent()

            # A headless freeplay agent charts its starting area only after the
            # snapshot system's initial bootstrap may already have entered
            # MAINTENANCE.  Reconcile every tracked chunk now and wait for the
            # writer to be fully idle before either DuckDB loader can admit the
            # actor.  This also makes native-save resume independent of stale
            # or missing host-side snapshot files.
            await self._reconcile_snapshot_disk()
            await self._prepare_freeplay_snapshot()

            # Load modules based on variant
            await self._load_embodied_actions()
            await self._load_reachable_view()

            # EventStream: infrastructure the orchestrator drains at the turn
            # boundary (API_AFFORDANCE_REDESIGN §2.5). Not agent-visible.
            await self._load_event_stream()

            if self.config.variant == RuntimeVariant.FULL:
                await self._load_database()
                await self._load_remote_view()

            # Load scenario adapter if a known scenario is detected
            await self._load_scenario_adapter()

            # Note: We intentionally do NOT inject boilerplate into Jupyter kernel.
            # The boilerplate creates its own RCON/UDP connections which conflict
            # with Tier 3's connections. Instead, code execution uses in-process
            # execution with Tier 4's modules, and results are logged to notebook.

            self._set_state(TierState.READY)

        except Exception as e:
            self._set_state(TierState.ERROR, str(e))
            raise TierInitializationError(self.tier_level, str(e)) from e

    async def _setup_session_dir(self) -> Optional[Path]:
        """Setup session directory for this agent run.

        Session structure depends on session_mode:
        - LLM: .fv-output/runs/{provider}/{model}/{run_id}/ (full LLM artifacts)
        - EVAL: .fv-output/evals/{task_name}/{run_id}/ (trajectory + notebook only)
        - NONE: No session directory (testing only)

        Both LLM and EVAL modes create trajectory.jsonl and notebook.ipynb for
        reproducibility. LLM mode additionally creates system_prompt.md, initial_state.md, etc.
        """
        # Check for explicit session_dir override first
        if self.config.session_dir:
            session_dir = self.config.session_dir
            session_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Tier 4: Using explicit session directory: {session_dir}")
            return session_dir

        session_mode = self.config.session_mode

        # NONE mode: no session directory (for lightweight testing)
        if session_mode == SessionMode.NONE:
            logger.info("Tier 4: SessionMode.NONE - no session directory")
            return None

        # EVAL mode: create eval-specific session structure
        if session_mode == SessionMode.EVAL:
            return await self._setup_eval_session_dir()

        # LLM mode: create full LLM session structure
        return await self._setup_llm_session_dir()

    async def _setup_eval_session_dir(self) -> Path:
        """Setup session directory for evaluation runs.

        Directory structure: .fv-output/evals/{task_name}/{run_id}/

        Artifacts created:
        - config.json: Task + environment configuration
        - trajectory.jsonl: Mechanistic source of truth
        - notebook.ipynb: Reproducibility (via _setup_executor)
        - result.json: Verification result (written by eval harness, not here)
        """
        import datetime
        import json

        infra_config = self._env.config.infra_config
        task_name = self.config.task_name or "unknown_task"
        run_id = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

        # Directory: .fv-output/evals/{task_name}/{run_id}/
        session_dir = infra_config.fv_output_dir / "evals" / task_name / run_id
        session_dir.mkdir(parents=True, exist_ok=True)

        # Write config.json with task and environment settings
        config_data = {
            "task_name": task_name,
            "run_id": run_id,
            "agent_id": self.config.agent_id,
            "scenario": self._env.config.tier2.scenario if self._env.config.tier2 else None,
            "variant": self.config.variant.value if hasattr(self.config.variant, 'value') else self.config.variant,
            "started_at": datetime.datetime.now().isoformat(),
        }

        config_path = session_dir / "config.json"
        with open(config_path, "w") as f:
            json.dump(config_data, f, indent=2)

        logger.info(f"Tier 4: Eval session directory: {session_dir}")
        logger.info(f"Tier 4: Task: {task_name}, Run ID: {run_id}")
        return session_dir

    async def _setup_llm_session_dir(self) -> Path:
        """Setup session directory for LLM agent runs.

        Directory structure: .fv-output/runs/{provider}/{model}/{run_id}/

        Uses FileManager for consistent session structure with full LLM artifacts.
        """
        from FactoryVerse.infra.session.file_manager import FileManager

        infra_config = self._env.config.infra_config

        # Get provider from config hierarchy:
        # 1. RuntimeConfig.provider (explicit)
        # 2. InteractionConfig.llm_provider (from tier 6)
        # 3. Default to "unknown"
        provider = self.config.provider
        if not provider:
            provider = self._env.config.tier6.llm_provider if self._env.config.tier6 else None
        if not provider:
            provider = "unknown"

        # Get model name from config hierarchy:
        # 1. RuntimeConfig.model (explicit)
        # 2. InteractionConfig.model (from tier 6)
        # 3. Default to "unknown"
        model_name = self.config.model
        if not model_name:
            model_name = self._env.config.tier6.model if self._env.config.tier6 else None
        if not model_name:
            model_name = "unknown"

        # Get mode from config hierarchy
        mode = self.config.mode
        if not mode:
            mode = self._env.config.tier6.mode if self._env.config.tier6 else "autonomous"

        # Create session using FileManager
        # Directory structure: .fv-output/runs/{provider}/{model}/{run_id}/
        file_manager = FileManager(output_dir=infra_config.fv_output_dir)
        file_manager.initialize()

        session_config = file_manager.create_session(
            model=model_name,
            mode=mode,
            provider=provider,
        )

        # Store session config for later metadata updates
        self._session_config = session_config

        # Get session paths
        paths = file_manager.get_session_paths(session_config)
        session_dir = paths.session_dir

        logger.info(f"Tier 4: LLM session directory: {session_dir}")
        logger.info(f"Tier 4: Session ID: {session_config.run_id}")
        return session_dir

    async def _setup_trajectory_writer(self) -> None:
        """Setup trajectory writer for mechanistic event logging.

        The trajectory writer is the source of truth for what happened during a run.
        Both LLM and eval sessions use this - it's about the game run, not the LLM.

        For SessionMode.NONE, no trajectory is created.
        """
        if self._session_dir is None:
            # SessionMode.NONE - no trajectory
            logger.info("Tier 4: No session directory, skipping trajectory writer")
            return

        from FactoryVerse.infra.session.trajectory import TrajectoryWriter

        trajectory_path = self._session_dir / "trajectory.jsonl"
        self._trajectory_writer = TrajectoryWriter(trajectory_path)

        # Write run_start event with basic metadata
        # Note: LLM sessions will add llm_session_start via Tier 6
        session_mode = self.config.session_mode
        task_name = self.config.task_name

        # Use a generic run_start that works for both eval and LLM modes
        # The trajectory writer's session_start takes model/mode which are LLM concepts
        # For eval, we'll write a simpler start event
        if session_mode == SessionMode.EVAL:
            # For eval, write a minimal start event
            self._trajectory_writer._write(
                "run_start",
                session_mode="eval",
                task_name=task_name,
                agent_id=self._agent_id,
                scenario=self._env.config.tier2.scenario if self._env.config.tier2 else None,
            )
        else:
            # For LLM mode, Tier 6 will call session_start with model/mode
            # Just log that trajectory is ready
            pass

        logger.info(f"Tier 4: Trajectory writer initialized: {trajectory_path}")
        self._modules_loaded.append("trajectory_writer")

    async def _setup_executor(self) -> None:
        """Setup execution environment for code execution.

        Code execution always uses in-process execution (exec) with Tier 4 modules.
        In JUPYTER mode, we also create a notebook file for logging executions.
        """
        execution_mode = self.config.execution_mode

        if execution_mode == ExecutionMode.JUPYTER:
            import nbformat

            # Create notebook path in session directory
            if self._session_dir is None:
                raise RuntimeError("Session directory must be set before creating executor")

            self._notebook_path = self._session_dir / "agent_session.ipynb"

            # Create empty notebook file (we'll log executions to it)
            self._notebook_path.parent.mkdir(parents=True, exist_ok=True)
            nb = nbformat.v4.new_notebook()
            nb.metadata.update({
                "kernelspec": {
                    "display_name": "Python 3",
                    "language": "python",
                    "name": "python3",
                }
            })
            with open(self._notebook_path, "w") as f:
                nbformat.write(nb, f)

            # Mark that we have notebook logging (executor is None for in-process)
            self._executor = None  # We use in-process execution, not kernel
            logger.info(f"Tier 4: Notebook logging enabled: {self._notebook_path}")

        elif execution_mode == ExecutionMode.INPROCESS:
            # No notebook, just in-process execution
            self._executor = None
            self._notebook_path = None
            logger.info("Tier 4: InProcess execution mode (no notebook)")

        self._modules_loaded.append("executor")

    def _calculate_agent_udp_port(self, agent_id: str) -> int:
        """Calculate the correct UDP port for an agent.

        Each agent needs a unique UDP port for async action notifications.
        Port allocation is deterministic based on agent_id and instance type:
        - Client: base_port + agent_index
        - Server N: base_port + (N * max_agents) + agent_index

        Args:
            agent_id: Agent identifier (e.g., 'agent_1', 'agent_2')

        Returns:
            UDP port number for this agent
        """
        tier3 = self._env.tier3
        infra_config = self._env.config.infra_config

        # Extract agent index from agent_id (e.g., "agent_1" -> 0, "agent_2" -> 1)
        try:
            agent_index = int(agent_id.split("_")[1]) - 1  # Convert to 0-based
        except (ValueError, IndexError):
            agent_index = 0

        # Determine server_index from tier3 instance
        server_index = None
        if tier3 and tier3.instance and tier3.instance.startswith("server_"):
            try:
                server_index = int(tier3.instance.split("_")[1])
            except (ValueError, IndexError):
                pass

        return infra_config.get_agent_port(agent_index, server_index)

    def _calculate_agent_turn_port(self, agent_id: str) -> int:
        """UDP port for the agent's `turn` stream (same stride as the action port)."""
        tier3 = self._env.tier3
        infra_config = self._env.config.infra_config
        try:
            agent_index = int(agent_id.split("_")[1]) - 1
        except (ValueError, IndexError):
            agent_index = 0
        server_index = None
        if tier3 and tier3.instance and tier3.instance.startswith("server_"):
            try:
                server_index = int(tier3.instance.split("_")[1])
            except (ValueError, IndexError):
                pass
        return infra_config.get_agent_turn_port(agent_index, server_index)

    def _turn_stream_file(self) -> Optional[Path]:
        """The agent's turn.jsonl under this instance's script-output, if resolvable."""
        tier3 = self._env.tier3
        if tier3 is None or tier3.instance is None or self._agent_numeric_id is None:
            return None
        try:
            base = self._env.config.infra_config.get_script_output_dir(tier3.instance)
        except Exception:
            return None
        return base / "factoryverse" / "agent-snapshots" / str(self._agent_numeric_id) / "turn.jsonl"

    async def _start_turn_stream(self, turn_port: int) -> None:
        """Bind the turn port and adopt Lua's (epoch, seq) — the honest attach."""
        from FactoryVerse.game.agent.infra.turn_stream import TurnStreamListener, queue_deliverer

        tier3 = self._env.tier3
        if tier3 is None or tier3._action_listener is None or self._agent_numeric_id is None:
            logger.warning("Tier 4: turn stream not started (no listener or agent id)")
            return
        numeric_id = self._agent_numeric_id
        listener = TurnStreamListener(
            port=turn_port,
            file_path=self._turn_stream_file(),
            state_source=lambda: tier3.stream_state(numeric_id, "turn"),
            deliver=queue_deliverer(tier3._action_listener.notification_queue),
        )
        listener.start()
        self._turn_stream = listener
        self._modules_loaded.append("turn_stream")

    async def _reconcile_and_create_agent(self) -> None:
        """Reconcile agent state: Query Lua first, then decide action.

        Strategy (Lua is SSOT):
        1. Query tier3.list_game_agents()
        2. Find agent by interface_name
        3. If exists + entity_valid + port matches: BIND
        4. If exists + wrong port or invalid entity: DESTROY then CREATE
        5. If not exists: CREATE
        6. Update Python AgentRegistry as metadata (optional)
        """
        from datetime import datetime
        from uuid import uuid4
        from FactoryVerse.game.agent.core.profile import AgentProfile, AgentStatus

        tier3 = self._env.tier3
        if tier3 is None:
            raise RuntimeError("Tier 3 must be initialized")

        # Get requested agent ID and calculate UDP port
        requested_id = self.config.agent_id or "agent_1"
        udp_port = self._calculate_agent_udp_port(requested_id)
        turn_port = self._calculate_agent_turn_port(requested_id)

        # Step 1: Query Lua for existing agents (SSOT)
        game_agents = tier3.list_game_agents()
        existing = next(
            (a for a in game_agents if a.get("interface_name") == requested_id),
            None,
        )

        if existing:
            # Agent exists in Factorio - check if we can bind or need to recreate
            existing_port = existing.get("udp_port")
            existing_turn_port = existing.get("turn_port")
            entity_valid = existing.get("entity_valid", True)

            if entity_valid and existing_port == udp_port and existing_turn_port == turn_port:
                # Case 1: BIND - Agent is valid with correct port
                # Use Lua's interface_name (may differ from requested_id)
                lua_interface = existing.get("interface_name")
                if lua_interface:
                    self._agent_id = lua_interface
                self._agent_numeric_id = existing.get("id")
                logger.info(
                    f"Tier 4: Binding to existing agent '{self._agent_id}' "
                    f"(port {udp_port}, entity valid)"
                )
            else:
                # Case 2: DESTROY then CREATE - Port mismatch or invalid entity
                reason = []
                if not entity_valid:
                    reason.append("entity invalid")
                if existing_port != udp_port:
                    reason.append(f"port mismatch ({existing_port} != {udp_port})")
                if existing_turn_port != turn_port:
                    reason.append(f"turn port mismatch ({existing_turn_port} != {turn_port})")

                logger.info(
                    f"Tier 4: Recreating agent '{requested_id}' ({', '.join(reason)})"
                )

                # Destroy the existing agent
                agent_numeric_id = existing.get("id")
                if agent_numeric_id is not None:
                    tier3.destroy_game_agents([agent_numeric_id])

                # Create new agent with correct configuration
                result = tier3.create_game_agent(
                    udp_port=udp_port,
                    set_unique_forces=False,
                    default_common_force="player",
                    initial_inventory=self.config.initial_inventory,
                    turn_port=turn_port,
                )
                # Use Lua's assigned interface_name (agent_{numeric_id})
                if result and result.get("interface_name"):
                    self._agent_id = result["interface_name"]
                    self._agent_numeric_id = result.get("agent_id")
                    logger.info(f"Tier 4: Recreated agent, using interface '{self._agent_id}'")
        else:
            # Case 3: CREATE - No existing agent
            logger.info(f"Tier 4: Creating new agent '{requested_id}' (port {udp_port})")
            result = tier3.create_game_agent(
                udp_port=udp_port,
                set_unique_forces=False,
                default_common_force="player",
                initial_inventory=self.config.initial_inventory,
                turn_port=turn_port,
            )
            # Use Lua's assigned interface_name (agent_{numeric_id})
            if result and result.get("interface_name"):
                self._agent_id = result["interface_name"]
                self._agent_numeric_id = result.get("agent_id")
                logger.info(f"Tier 4: Created agent, using interface '{self._agent_id}'")

        # Update Python AgentRegistry as metadata (optional)
        registry = tier3.agent_registry
        if registry:
            profile = registry.get_by_name(requested_id)
            if not profile:
                # Create new profile
                profile = AgentProfile(
                    id=uuid4(),
                    name=requested_id,
                    instance_id=tier3.instance or "unknown",
                    model=self._env.config.tier6.model
                    if self._env.config.tier6
                    else "unknown",
                    description="Auto-generated by Tier 4 Runtime",
                    status=AgentStatus.ACTIVE,
                )
                registry.register(profile)
                logger.debug(f"Tier 4: Created profile for agent '{requested_id}'")
            else:
                # Update existing profile
                profile.status = AgentStatus.ACTIVE
                profile.updated_at = datetime.now()
                registry.save(profile)
                logger.debug(f"Tier 4: Updated profile for agent '{requested_id}'")

        # Refresh interfaces to pick up the agent
        if tier3.rcon_helper:
            tier3.rcon_helper.refresh_interfaces()

        self._modules_loaded.append("agent")
        logger.info(f"Tier 4: Agent '{self._agent_id}' ready on UDP port {udp_port}")

        # The agent's `turn` stream: bind its port and adopt Lua's (epoch, seq).
        await self._start_turn_stream(turn_port)

    async def _reconcile_snapshot_disk(self, timeout: float = 300.0) -> None:
        """If the mod's storage says chunks are snapshotted but the host-side
        snapshot directory holds no chunk files, ask the mod to run its boot
        pass (``remote.call("map","boot")``) and wait for the queue to drain.

        Found live 2026-08-29: a save carries its snapshot bookkeeping, the
        host directory does not; loading the save gives on_load only, so the
        files are never rewritten and the loader reads an empty world as a
        healthy one (Constitution §15).
        """
        tier3 = self._env.tier3
        if tier3 is None or tier3.map_api is None:
            return
        try:
            report = tier3.run_lua('return remote.call("map", "get_boot_report")') or {}
        except Exception as e:  # older mod without the probe — nothing to reconcile
            logger.debug("get_boot_report unavailable: %s", e)
            return
        tracker = (report.get("tracker") or {}) if isinstance(report, dict) else {}
        snapshotted = int(tracker.get("snapshotted") or 0)
        if snapshotted <= 0:
            return
        snapshot_dir = None
        try:
            snapshot_dir = self._env.config.tier1.get_snapshot_dir(tier3.instance) if tier3.instance else None
        except Exception:
            snapshot_dir = None
        if snapshot_dir is None:
            return
        host_chunks = sum(1 for _ in Path(snapshot_dir).rglob("entities-init.jsonl"))
        if host_chunks > 0:
            return
        logger.warning(
            "Tier 4: mod storage says %d chunks snapshotted but %s holds no chunk files — requesting the boot pass",
            snapshotted, snapshot_dir,
        )
        tier3.run_lua('return remote.call("map", "boot", "host_disk_empty")')
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            report = tier3.run_lua('return remote.call("map", "get_boot_report")') or {}
            queue = (report.get("queue") or {}) if isinstance(report, dict) else {}
            if int(queue.get("pending") or 0) == 0 and report.get("phase") != "INITIAL_SNAPSHOTTING":
                break
            await asyncio.sleep(1.0)
        host_chunks = sum(1 for _ in Path(snapshot_dir).rglob("entities-init.jsonl"))
        if host_chunks == 0:
            raise RuntimeError(
                f"snapshot boot pass ran but {snapshot_dir} still holds no chunk files (report={report})"
            )

    async def _prepare_freeplay_snapshot(self, timeout: float = 300.0) -> None:
        """Re-snapshot all tracked freeplay chunks before loading DuckDB."""
        if self._env.config.tier2.scenario != "freeplay":
            return

        tier3 = self._env.tier3
        if tier3 is None or tier3.map_api is None:
            raise RuntimeError("Tier 3 map interface is required for freeplay snapshotting")

        map_api = tier3.map_api
        lookup = map_api.get_chunk_lookup()
        chunks: list[dict[str, int]] = []
        for key in lookup:
            try:
                chunk_x, chunk_y = str(key).split(",", 1)
                chunks.append({"x": int(chunk_x), "y": int(chunk_y)})
            except (TypeError, ValueError):
                logger.warning("Ignoring malformed snapshot chunk key: %r", key)

        # A brand-new headless game can still have an empty tracker for a few
        # ticks.  The embodied agent is at the origin and must at minimum see
        # the same 7x7 starting window chart_spawn_area() promises.
        if not chunks:
            chunks = [
                {"x": chunk_x, "y": chunk_y}
                for chunk_x in range(-3, 4)
                for chunk_y in range(-3, 4)
            ]

        trigger_tick = tier3.get_game_tick()
        result = map_api.re_snapshot_chunks(chunks)
        if not result.success or result.chunks_queued != len(chunks):
            raise RuntimeError(
                "Failed to queue complete freeplay snapshot: "
                f"queued={result.chunks_queued}, expected={len(chunks)}, "
                f"error={result.error}"
            )

        expected = {(chunk["x"], chunk["y"]) for chunk in chunks}
        deadline = time.monotonic() + timeout
        last_status: Any = None
        stale_count = len(expected)
        while time.monotonic() < deadline:
            last_status = map_api.get_snapshot_status()
            current_lookup = map_api.get_chunk_lookup()
            stale_count = 0
            for chunk_x, chunk_y in expected:
                entry = current_lookup.get(f"{chunk_x},{chunk_y}") or {}
                snapshot_tick = entry.get("snapshot_tick")
                if snapshot_tick is None or int(snapshot_tick) < trigger_tick:
                    stale_count += 1

            writer_idle = (
                last_status.chunks_processing == 0
                and last_status.chunks_pending == 0
            )
            if writer_idle and stale_count == 0:
                logger.info(
                    "Tier 4: Freeplay snapshot reconciled at tick %s (%s chunks)",
                    trigger_tick,
                    len(expected),
                )
                return
            await asyncio.sleep(0.5)

        raise asyncio.TimeoutError(
            "Freeplay snapshot reconciliation did not quiesce within "
            f"{timeout}s (stale_chunks={stale_count}, status={last_status})"
        )

    async def _load_embodied_actions(self) -> None:
        """Load EmbodiedActions modules.

        Loads individual action classes: MovementAction, PlacementAction, etc.
        """
        tier3 = self._env.tier3
        if tier3 is None or tier3.rcon_helper is None:
            raise RuntimeError("Tier 3 must be initialized with RCON")

        # Use RconHandler for agent-specific actions (legacy compatibility)
        from FactoryVerse.game.agent.infra.rcon_handler import RconHandler

        rcon_handler = RconHandler(tier3.rcon_helper.rcon_client, self.agent_id)

        if tier3._action_listener is None:
            raise RuntimeError("Tier 3 UDP listener not initialized")
        async_listener = tier3._action_listener  # From tier3 UDP setup

        # Import action classes
        from FactoryVerse.game.agent.embodied_actions.walking import MovementAction
        from FactoryVerse.game.agent.embodied_actions.place_entity import PlacementAction
        from FactoryVerse.game.agent.embodied_actions.entity_operations import (
            EntityOperationsAction,
        )
        from FactoryVerse.game.agent.embodied_actions.inventory import AgentInventory
        from FactoryVerse.game.agent.embodied_actions.crafting import CraftingAction
        from FactoryVerse.game.agent.embodied_actions.research import ResearchAction
        from FactoryVerse.game.agent.embodied_actions.mining import MiningAction

        # Create action instances in dependency order
        self._entity_ops = EntityOperationsAction(rcon_handler)
        self._movement = MovementAction(rcon_handler, async_listener)
        self._mining = MiningAction(rcon_handler, async_listener)
        self._placement = PlacementAction(
            rcon_handler, self._entity_ops, self._movement
        )
        self._inventory = AgentInventory(rcon_handler, self._placement)
        self._crafting = CraftingAction(rcon_handler, async_listener)
        self._inventory._attach_crafting(self._crafting)  # await_item reads the queue, never writes
        self._research = ResearchAction(rcon_handler)
        from FactoryVerse.game.agent.entity_reference import EntityReferenceAccessor

        self._entity_reference = EntityReferenceAccessor(rcon_handler)

        # Store as dict for easy access
        self._embodied_actions = {
            "movement": self._movement,
            "placement": self._placement,
            "entity_ops": self._entity_ops,
            "inventory": self._inventory,
            "crafting": self._crafting,
            "research": self._research,
            "mining": self._mining,
        }
        self._modules_loaded.append("embodied_actions")

        logger.info("Tier 4: EmbodiedActions loaded (7 action modules)")

    async def _load_reachable_view(self) -> None:
        """Load ReachableView module (Lua-based entity querying)."""
        from FactoryVerse.game.agent.reachable_view import ReachableView
        from FactoryVerse.game.agent.infra.rcon_handler import RconHandler

        tier3 = self._env.tier3
        if tier3 is None or tier3.rcon_helper is None:
            raise RuntimeError("Tier 3 must be initialized with RCON")

        # ReachableView requires RconHandler (not RconHelper)
        rcon_handler = RconHandler(tier3.rcon_helper.rcon_client, self.agent_id)

        # ReachableView requires action instances
        self._reachable_view = ReachableView(
            rcon_handler=rcon_handler,
            entity_ops=self._entity_ops,
            place_ops=self._placement,
            walking_action=self._movement,
            mining_action=self._mining,
        )
        self._modules_loaded.append("reachable_view")

        logger.info("Tier 4: ReachableView loaded")

    async def _load_event_stream(self) -> None:
        """Load EventStream for temporal perception of game events.

        The EventStream wraps Tier 3's notification queue to provide a clean,
        typed API for consuming asynchronous game events. This is the temporal
        complement to spatial views (ReachableView, RemoteView).

        Events include:
        - Research completions (unlocks new capabilities)
        - Crafting completions (for fire-and-forget NQ/DQ pattern)
        - Other game state changes
        """
        from FactoryVerse.game.agent.event_stream import EventStream

        tier3 = self._env.tier3
        if tier3 is None or tier3._action_listener is None:
            logger.warning("Tier 4: Skipping EventStream (no action listener)")
            return

        # Get notification queue from Tier 3's AsyncActionListener
        notification_queue = tier3._action_listener.notification_queue

        self._event_stream = EventStream(
            notification_queue=notification_queue,
            listener=tier3._action_listener,
        )
        self._modules_loaded.append("event_stream")

        logger.info("Tier 4: EventStream loaded (temporal perception)")

    async def _load_scenario_adapter(self) -> None:
        """Load scenario adapter if a known scenario is detected.

        Auto-detects the running scenario by checking for registered scenario
        remote interfaces (e.g., lab_grid). If found, loads the corresponding
        Python adapter for type-safe access to scenario-specific capabilities.

        For lab-grid, injects database and snapshot_dir for orchestration support.

        The loaded adapter is accessible via `self.scenario`.
        """
        from FactoryVerse.game.scenarios import detect_scenario
        from FactoryVerse.game.scenarios.lab_grid import LabGridAdapter

        tier3 = self._env.tier3
        if tier3 is None or tier3.rcon_helper is None:
            logger.debug("Tier 4: Skipping scenario adapter (no RCON)")
            return

        rcon_client = tier3.rcon_helper.rcon_client
        scenario_name = detect_scenario(rcon_client)

        if scenario_name == "lab-grid":
            # Lab-grid gets database and snapshot_dir for orchestration
            infra_config = self._env.config.infra_config
            snapshot_dir = infra_config.get_snapshot_dir(tier3.instance) if tier3.instance else None

            self._scenario_adapter = LabGridAdapter(
                rcon=rcon_client,
                database=self._database,
                snapshot_dir=snapshot_dir,
            )
            self._modules_loaded.append("scenario:lab-grid")
            logger.info("Tier 4: Loaded LabGridAdapter with orchestration support")
        elif scenario_name is not None:
            # Other scenarios use default adapter loading
            from FactoryVerse.game.scenarios import get_scenario_adapter
            adapter = get_scenario_adapter(scenario_name, rcon_client)
            if adapter:
                self._scenario_adapter = adapter
                self._modules_loaded.append(f"scenario:{scenario_name}")
                logger.info(f"Tier 4: Loaded scenario adapter: {scenario_name}")
        else:
            logger.debug("Tier 4: No known scenario detected")

    async def _load_database(self) -> None:
        """Load DuckDB database for persistent game state."""
        from FactoryVerse.game.infra.duckdb.database import SnapshotDatabase

        # Use in-memory database (session_dir is optional for testing)
        # For persistent storage, pass db_path to SnapshotDatabase
        self._snapshot_database = SnapshotDatabase(db_path=None)  # In-memory
        self._snapshot_database.ensure_schema()
        self._database = self._snapshot_database.connection
        self._modules_loaded.append("database")

        # Sync with game state
        await self._sync_database()

        logger.info("Tier 4: DuckDB connected (in-memory)")

    async def _wait_for_snapshot_bootstrap(self, timeout: float = 120.0) -> None:
        """Wait for Lua snapshot system bootstrap to complete before loading data.

        The snapshot system has two phases:
        - INITIAL_SNAPSHOTTING: Bootstrap phase, still discovering and writing chunks
        - MAINTENANCE: Bootstrap complete, stable state for loading

        This method polls RCON to check the snapshot system phase and waits
        until MAINTENANCE phase is reached (or timeout).

        Args:
            timeout: Maximum time to wait for bootstrap (seconds, default 120s)

        Raises:
            asyncio.TimeoutError: If bootstrap doesn't complete within timeout
        """
        tier3 = self._env.tier3
        if tier3 is None or tier3.map_api is None:
            raise RuntimeError("Tier 3 must be initialized with RCON")

        map_api = tier3.map_api
        start_time = time.time()
        check_interval = 1.0  # Check every second
        last_log_time = 0.0

        logger.info("Tier 4: Waiting for snapshot system bootstrap to complete...")

        while True:
            elapsed = time.time() - start_time

            # Check timeout
            if elapsed > timeout:
                raise asyncio.TimeoutError(
                    f"Snapshot bootstrap did not complete within {timeout}s. "
                    "The game may still be in INITIAL_SNAPSHOTTING phase."
                )

            # Poll snapshot status via adapter
            try:
                status = map_api.get_snapshot_status()
                system_phase = status.system_phase

                if system_phase in ("MAINTENANCE", "EMPTY"):
                    # Bootstrap complete!
                    logger.info(
                        f"Tier 4: Snapshot bootstrap complete! "
                        f"{status.chunks_snapshotted} chunks snapshotted, entering MAINTENANCE mode."
                    )
                    return

                elif system_phase == "INITIAL_SNAPSHOTTING":
                    # Still bootstrapping - log progress periodically
                    # Log every 5 seconds
                    if elapsed - last_log_time >= 5.0:
                        last_log_time = elapsed
                        logger.info(
                            f"Tier 4: Processing chunks: {status.chunks_pending} pending, "
                            f"{status.chunks_snapshotted} completed"
                        )

                else:
                    # Unknown phase - treat as still bootstrapping
                    logger.debug(f"Tier 4: Unknown snapshot phase: {system_phase}")

            except Exception as e:
                logger.warning(f"Tier 4: Error checking snapshot status: {e}")

            await asyncio.sleep(check_interval)

    async def _sync_database(self) -> None:
        """Sync DuckDB with game state from snapshots.

        This method:
        1. Waits for snapshot system bootstrap to complete (MAINTENANCE phase)
        2. Loads initial snapshot data
        3. Reloads after bootstrap to ensure complete data
        """
        # Get snapshot directory based on instance
        tier3 = self._env.tier3
        if tier3 is None or tier3.instance is None:
            raise RuntimeError("Tier 3 must be initialized with instance")
        infra_config = self._env.config.infra_config

        snapshot_dir = infra_config.get_snapshot_dir(tier3.instance)

        # Use snapshot loader to sync database
        from FactoryVerse.game.infra.duckdb.loader import SnapshotLoader

        if self._database is None:
            raise RuntimeError("Database not initialized")

        loader = SnapshotLoader(
            db=self._database,
            snapshot_dir=snapshot_dir,
        )

        # CRITICAL: Wait for snapshot system bootstrap to complete
        # Without this, we may load incomplete/stale data
        await self._wait_for_snapshot_bootstrap(timeout=120.0)

        # Now load snapshot data - system is in MAINTENANCE mode
        # Pass game.tick so previous-boot files ("from the future") are
        # skipped instead of loaded as live data (CELL-2a)
        current_game_tick = self._safe_game_tick()
        logger.info(
            f"Tier 4: Loading snapshot data into database "
            f"(game tick guard: {current_game_tick})..."
        )
        loader.load_all(current_game_tick=current_game_tick)

        logger.info("Tier 4: Database synced with game state (bootstrap complete)")

    def _safe_game_tick(self) -> Optional[int]:
        """Current game tick via tier3 RCON, or None (guard disabled)."""
        tier3 = self._env.tier3
        if tier3 is None:
            return None
        try:
            return tier3.get_game_tick()
        except Exception as e:
            logger.warning(f"Tier 4: Could not fetch game tick for load guard: {e}")
            return None

    async def _load_remote_view(self) -> None:
        """Load RemoteView module (SQL-based entity querying).

        IMPORTANT: RemoteView needs a SEPARATE UDP dispatcher on the snapshot port,
        not the agent action port. The snapshot system sends entity updates
        (created, destroyed, etc.) on a different port than agent action completions.

        Port separation:
        - Agent action port (34202+): Walking/mining/crafting completion notifications
        - Snapshot port (34500 for client, 34400+N for servers): Entity state updates
        """
        from FactoryVerse.game.agent.remote_view import RemoteView
        from FactoryVerse.infra.udp_dispatcher import UDPDispatcher, get_udp_dispatcher

        tier3 = self._env.tier3
        if tier3 is None:
            raise RuntimeError("Tier 3 must be initialized")
        infra_config = self._env.config.infra_config
        if tier3 is None or tier3.instance is None:
            raise RuntimeError("Tier 3 must be initialized with instance")
        snapshot_dir = infra_config.get_snapshot_dir(tier3.instance)

        # DB-VISION-1: RemoteView treats udp_dispatcher=None as "sync disabled" —
        # there is NO global-dispatcher fallback inside it (load() sets _sync=None,
        # start() returns early). Passing None here froze the eval DB at its
        # boot-time load for the entire 2026-07-11 terra-pro run. We must hand it
        # a dispatcher bound to the instance's SNAPSHOT port (34400+N for servers —
        # the only snapshot port socat forwards; 34500 for client). Pin the global
        # singleton to that port BEFORE RemoteView's bootstrap wait creates it on
        # the client default, so the phase-change UDP leg listens correctly too.
        snapshot_udp_port = infra_config.get_snapshot_port(tier3.instance)
        udp_dispatcher = get_udp_dispatcher(port=snapshot_udp_port)
        if udp_dispatcher.port != snapshot_udp_port:
            logger.warning(
                f"Tier 4: global UDP dispatcher already bound to port "
                f"{udp_dispatcher.port}, need snapshot port {snapshot_udp_port} — "
                f"creating a dedicated dispatcher for RemoteView sync"
            )
            udp_dispatcher = UDPDispatcher(port=snapshot_udp_port)
        if not udp_dispatcher.is_running():
            await udp_dispatcher.start()
        logger.info(
            f"Tier 4: RemoteView sync dispatcher on snapshot port {udp_dispatcher.port}"
        )

        self._remote_view = RemoteView(
            snapshot_dir=snapshot_dir,
            entity_ops=self._entity_ops,
            place_ops=self._placement,
            walking_action=self._movement,
            mining_action=self._mining,
            db_path=self.config.database_path,
            udp_dispatcher=udp_dispatcher,
            rcon_client=tier3._rcon,
        )

        # Load initial data and start sync service
        # Note: load() will start the global UDP dispatcher internally
        logger.info("Tier 4: Loading RemoteView data...")
        set_agent = getattr(self._remote_view, "set_agent_id", None)
        if set_agent is not None:
            set_agent(self._agent_numeric_id)  # remote_view.production() needs the force's agent
        await self._remote_view.load(wait_for_bootstrap=True, bootstrap_timeout=120.0)
        await self._remote_view.start()  # Start real-time sync via UDP
        self._mining.set_resource_depletion_barrier(
            self._remote_view.wait_for_resource_depletion,
            self._remote_view.capture_resource_depletion_baseline,
        )
        self._placement.set_state_barrier(self._remote_view.wait_for_placement)
        logger.info("Tier 4: RemoteView sync started")

        self._modules_loaded.append("remote_view")
        logger.info("Tier 4: RemoteView loaded")

    async def verify_ready(self) -> Tier4Status:
        """Verify runtime is operational."""
        if self._state != TierState.READY:
            return Tier4Status(
                state=self._state,
                error=self._error,
            )

        db_connected = self._database is not None
        db_synced = db_connected  # Simplified - would have more checks

        return Tier4Status(
            state=self._state,
            runtime_initialized=True,
            database_connected=db_connected
            if self.config.variant == RuntimeVariant.FULL
            else None,
            database_synced=db_synced
            if self.config.variant == RuntimeVariant.FULL
            else None,
            modules_loaded=self._modules_loaded,
        )

    async def reset(self) -> None:
        """Reset runtime by reloading modules."""
        await self.shutdown()
        await self.initialize()

    async def shutdown(self, total_turns: Optional[int] = None) -> None:
        """Shutdown runtime and cleanup.

        Args:
            total_turns: Final turn count to save in session metadata
        """
        self._set_state(TierState.SHUTTING_DOWN)

        # Save session metadata before cleanup
        if self._session_config is not None:
            self._save_session_metadata(total_turns=total_turns)

        # Clear executor and notebook path
        self._executor = None
        self._notebook_path = None

        # Note: We don't stop the global UDP dispatcher here since it's shared
        # and managed by the infra module. RemoteView uses get_udp_dispatcher()
        # which returns the global singleton.

        # Close database via SnapshotDatabase wrapper
        if self._snapshot_database:
            try:
                self._snapshot_database.close()
            except Exception:
                pass
            self._snapshot_database = None
            self._database = None

        # Stop the turn stream listener (it owns a socket thread)
        turn_stream = getattr(self, "_turn_stream", None)
        if turn_stream is not None:
            try:
                turn_stream.stop()
            except Exception:
                pass
            self._turn_stream = None

        # Clear module references
        self._remote_view = None
        self._reachable_view = None
        self._embodied_actions = None
        self._entity_reference = None
        self._scenario_adapter = None
        self._event_stream = None
        self._agent_id = None
        self._agent_numeric_id = None

        # Clear persistent user namespace
        self._user_namespace = {}
        self._session_dir = None
        self._session_config = None
        self._modules_loaded = []

        self._set_state(TierState.SHUTDOWN)

    def _save_session_metadata(self, total_turns: Optional[int] = None) -> None:
        """Save session metadata to disk.

        Args:
            total_turns: Final turn count
        """
        if self._session_config is None or self._session_dir is None:
            return

        from FactoryVerse.infra.session.file_manager import FileManager

        try:
            # Mark session as ended
            self._session_config.mark_ended(total_turns=total_turns)

            # Save metadata using FileManager
            infra_config = self._env.config.infra_config
            file_manager = FileManager(output_dir=infra_config.fv_output_dir)
            file_manager.save_metadata(self._session_config)

            logger.info(f"Tier 4: Session metadata saved (turns: {total_turns})")
        except Exception as e:
            logger.warning(f"Tier 4: Failed to save session metadata: {e}")

    _ALL_BUILTIN_NAMES = frozenset(
        {"agent_id", "walking", "inventory", "crafting", "research", "reachable_view",
         "remote_view", "entity_reference", "rcon_client", "runtime", "scenario", "plan"}
    )

    # TURN_CONTRACT §6 — the planning turn's namespace is a FILTER over the one
    # assembly below, never a second assembly site. Map-scale reads, research,
    # the inventory read, the agent's id, and the plan helper; no body verbs.
    PLANNING_NAMESPACE = frozenset(
        {"json", "asyncio", "agent_id", "remote_view", "entity_reference", "research", "inventory", "plan",
         "MapPosition", "TilePosition", "Direction", "BoundingBox",
         "ResearchStatus", "ResearchQueueItem", "QueuedTechnology"}
    )

    def set_plan_store(self, store: Any) -> None:
        """Bind the planning turn's plan helper (TURN_CONTRACT §6)."""
        self._plan_store = store

    async def execute_code(
        self, code: str, compress_output: bool = False, mode: str = "gameplay"
    ) -> str:
        """Execute Python code using in-process execution with notebook logging.

        ``mode``: "gameplay" binds the full namespace; "planning" binds only
        ``PLANNING_NAMESPACE`` (a body verb then raises NameError, which is the
        honest refusal — the verb does not exist in this turn).

        Code runs in the current process using exec() with access to Tier 4 modules
        (walking, crafting, mining, etc.). If JUPYTER mode is configured,
        the execution is also logged to the notebook for debugging.

        Args:
            code: Python code to execute
            compress_output: Whether to compress large outputs

        Returns:
            Output string from execution
        """
        import io
        import sys
        import json
        import asyncio
        import time

        # =================================================================
        # Import all types documented in API reference for agent use
        # =================================================================

        # Core spatial types
        from FactoryVerse.game.factory.types import (
            MapPosition,
            TilePosition,
            Direction,
            BoundingBox,
            # Status types
            CraftingQueueStatus,
            ResearchQueueItem,
        )

        # Connection-cue types (returned by connection_positions / sites)
        from FactoryVerse.game.agent.placement_hints import (
            ConnectionType,
            ConnectionPosition,
            WireConnectionPosition,
            EntityValidationError,
        )

        # Item types
        from FactoryVerse.game.factory.item.base import (
            Item,
            PlaceableItem,
            ItemStack,
        )

        # Walking exception types
        from FactoryVerse.game.agent.embodied_actions.walking import (
            WalkingError,
            WalkingUnreachableError,
            WalkingEntityNotFoundError,
            WalkingNoStandableTilesError,
        )

        # Research types
        from FactoryVerse.game.agent.embodied_actions.research import (
            ResearchStatus,
            QueuedTechnology,
        )

        tier3 = self._env.tier3

        # Create a runtime proxy for notification access
        # This allows notification code to access runtime._listener
        class RuntimeProxy:
            def __init__(self, listener):
                self._listener = listener
        runtime_proxy = RuntimeProxy(tier3._action_listener if tier3 else None)

        # Build namespace with Tier 4 modules
        # Start with user-defined variables from previous blocks
        namespace = dict(self._user_namespace)

        # Inject built-in modules (these override any user variables with same name)
        builtin_names = {
            "json": json,
            "asyncio": asyncio,
            # =================================================================
            # Core spatial types (MapPosition, Direction, BoundingBox)
            # =================================================================
            "MapPosition": MapPosition,
            "TilePosition": TilePosition,
            "Direction": Direction,
            "BoundingBox": BoundingBox,
            # =================================================================
            # Connection-cue types
            # =================================================================
            "ConnectionType": ConnectionType,
            "ConnectionPosition": ConnectionPosition,
            "WireConnectionPosition": WireConnectionPosition,
            "EntityValidationError": EntityValidationError,
            # =================================================================
            # Item types (Item, PlaceableItem, ItemStack)
            # =================================================================
            "Item": Item,
            "PlaceableItem": PlaceableItem,
            "ItemStack": ItemStack,
            # =================================================================
            # Status types (CraftingQueueStatus, ResearchStatus, etc.)
            # =================================================================
            "CraftingQueueStatus": CraftingQueueStatus,
            "ResearchStatus": ResearchStatus,
            "ResearchQueueItem": ResearchQueueItem,
            "QueuedTechnology": QueuedTechnology,
            # =================================================================
            # Walking exception types
            # =================================================================
            "WalkingError": WalkingError,
            "WalkingUnreachableError": WalkingUnreachableError,
            "WalkingEntityNotFoundError": WalkingEntityNotFoundError,
            "WalkingNoStandableTilesError": WalkingNoStandableTilesError,
            # =================================================================
            # Tier 4 components (action modules and views)
            # =================================================================
            # Eight names, each a human gesture (API_AFFORDANCE_REDESIGN §2.7).
            # Every verb on a thing in the world is a method of that thing; the
            # flat modules (placement, entity_ops, mining, verify,
            # placement_hints, events, the `resources` alias) were deleted
            # 2026-08-29 and their mechanisms live behind the objects.
            "agent_id": self._agent_id,
            "walking": self._movement,
            "inventory": self._inventory,
            "crafting": self._crafting,
            "research": self._research,
            "reachable_view": self._reachable_view,
            "remote_view": self._remote_view,
            "entity_reference": self._entity_reference,
        }

        # Raw transport and runtime internals are development capabilities, not
        # part of the production actor API. This narrows the cooperative actor
        # surface; an adversarial Python sandbox remains an outer-layer concern.
        if self.config.access_profile == RuntimeAccessProfile.DEBUG:
            builtin_names.update(
                {
                    "rcon_client": tier3.rcon if tier3 else None,
                    "runtime": runtime_proxy,
                    "scenario": self._scenario_adapter,
                }
            )
        if self._plan_store is not None:
            builtin_names["plan"] = self._plan_store
        if mode == "planning":
            builtin_names = {k: v for k, v in builtin_names.items() if k in self.PLANNING_NAMESPACE}
            # Body verbs defined by earlier gameplay blocks must not leak in
            # through the persistent user namespace either.
            for name in list(namespace):
                if name in self._ALL_BUILTIN_NAMES and name not in self.PLANNING_NAMESPACE:
                    namespace.pop(name, None)
        namespace.update(builtin_names)

        # Capture stdout
        stdout_capture = io.StringIO()
        old_stdout = sys.stdout
        start_time = time.time()
        error_text = None

        # A per-execution filename so a traceback frame can be attributed to
        # THIS block. A helper defined in an earlier block keeps that block's
        # filename, so its line numbers are never read against this source.
        self._exec_sequence += 1
        exec_filename = f"<execute_dsl:{self._exec_sequence}>"
        line_offset = 0

        try:
            sys.stdout = stdout_capture

            # Check if code contains 'await' - needs async execution
            if "await " in code:
                # Wrap code in async function that returns its locals
                indented_code = "\n".join(f"    {line}" for line in code.split("\n"))
                async_wrapper = f"async def __async_exec__():\n{indented_code}\n    return locals()\n"

                # The wrapper prepends one line, so traceback line numbers are
                # one ahead of the user's own source.
                line_offset = 1
                exec(compile(async_wrapper, exec_filename, "exec"), namespace)

                # Await the async function and capture its local variables
                async_locals = await namespace["__async_exec__"]()

                # Merge async locals back into namespace (excluding internals)
                for k, v in async_locals.items():
                    if not k.startswith("_"):
                        namespace[k] = v
            else:
                # Sync code - simple exec
                exec(compile(code, exec_filename, "exec"), namespace)

            # Persist user-defined variables for next code block
            for k, v in namespace.items():
                if k not in builtin_names and not k.startswith("_"):
                    self._user_namespace[k] = v

            output = stdout_capture.getvalue().strip()

        except Exception as e:
            output = stdout_capture.getvalue().strip()
            # Constitution §8: a call that fails without saying what it already
            # did is worse than a call that does nothing. Name the failing
            # line, and label output captured before the failure as work that
            # has already happened and will not be undone.
            error_text = _format_execution_error(e, code, exec_filename, line_offset)
            if output:
                output = (
                    "Output printed before the failure (this work already "
                    "happened and was not rolled back):\n"
                    f"{output}\n\n{error_text}"
                )
            else:
                output = error_text

        finally:
            sys.stdout = old_stdout

        execution_time = (time.time() - start_time) * 1000  # ms

        # Log to notebook if notebook logging is enabled
        if self._notebook_path is not None:
            self._log_to_notebook(code, output, error_text, execution_time)

        # Compress if requested
        if compress_output and output and not error_text:
            from FactoryVerse.infra.llm.context.compressor import OutputCompressor
            compressor = OutputCompressor()
            compressed = compressor.compress_action_result(output, action_type="execute_code")
            output = compressed.text

        return output

    def _log_to_notebook(
        self, code: str, output: str, error: Optional[str], execution_time_ms: float
    ) -> None:
        """Log code execution to notebook file.

        Args:
            code: Executed code
            output: Execution output
            error: Error message if any
            execution_time_ms: Execution time in milliseconds
        """
        if self._notebook_path is None:
            return

        import nbformat

        try:
            # Read existing notebook
            with open(self._notebook_path, "r") as f:
                nb = nbformat.read(f, as_version=4)

            # Create code cell
            cell = nbformat.v4.new_code_cell(source=code)
            cell.metadata["execution_time_ms"] = execution_time_ms

            # Add outputs
            cell_outputs = []
            if output:
                cell_outputs.append(
                    nbformat.v4.new_output(
                        output_type="stream",
                        name="stdout",
                        text=output,
                    )
                )
            if error:
                cell_outputs.append(
                    nbformat.v4.new_output(
                        output_type="error",
                        ename="ExecutionError",
                        evalue=error,
                        traceback=[error],
                    )
                )
            cell.outputs = cell_outputs

            nb.cells.append(cell)

            # Write back
            with open(self._notebook_path, "w") as f:
                nbformat.write(nb, f)

        except Exception as e:
            logger.warning(f"Tier 4: Failed to log to notebook: {e}")

    # =========================================================================
    # Module Reload
    # =========================================================================

    async def reload_modules(self) -> None:
        """Hot-reload Python modules.

        Useful during development to reload code changes
        without restarting the entire environment.
        """
        import importlib

        # List of modules to reload
        module_names = [
            "FactoryVerse.agent.embodied_actions",
            "FactoryVerse.agent.reachable_view",
            "FactoryVerse.agent.remote_view",
        ]

        for name in module_names:
            try:
                module = importlib.import_module(name)
                importlib.reload(module)
                logger.info(f"Tier 4: Reloaded {name}")
            except Exception as e:
                logger.warning(f"Tier 4: Failed to reload {name}: {e}")

        # Re-initialize module instances
        await self._load_embodied_actions()
        await self._load_reachable_view()
        if self.config.variant == RuntimeVariant.FULL:
            await self._load_remote_view()

    async def sync_database(self) -> None:
        """Force database sync with game state."""
        if self._database:
            await self._sync_database()

    def reload_snapshot_data(self) -> None:
        """Reload snapshot files into DuckDB without waiting for bootstrap.

        Use this after triggering a snapshot (e.g., via allocate_cell in lab-grid)
        when you know the snapshot files have been written but the bootstrap
        wait already completed earlier.

        Refreshes BOTH database holders (CELL-1 item 6): tier4's own
        SnapshotDatabase (legacy fallback for execute_duckdb) AND RemoteView's
        database (the connection actually served to agents via remote_view.query
        and the unified execute_duckdb path). Previously only tier4's was
        reloaded, so the two query paths served different truths.

        This is different from sync_database() which waits for bootstrap first.
        """
        if self._database is None:
            logger.warning("Tier 4: Cannot reload - database not initialized")
            return

        tier3 = self._env.tier3
        if tier3 is None or tier3.instance is None:
            logger.warning("Tier 4: Cannot reload - tier3 not initialized")
            return

        from FactoryVerse.game.infra.duckdb.loader import SnapshotLoader

        infra_config = self._env.config.infra_config
        snapshot_dir = infra_config.get_snapshot_dir(tier3.instance)

        loader = SnapshotLoader(
            db=self._database,
            snapshot_dir=snapshot_dir,
        )

        current_game_tick = self._safe_game_tick()
        logger.info(
            f"Tier 4: Reloading snapshot data into database "
            f"(game tick guard: {current_game_tick})..."
        )
        result = loader.load_all(current_game_tick=current_game_tick)
        logger.info(f"Tier 4: Snapshot reload complete - {result.entity_count} entities, {result.resource_count} resources")

        # ONE DB: rebuild RemoteView from the same files so remote_view.query
        # and execute_duckdb read the same post-allocation state
        if self._remote_view is not None and self._remote_view.is_loaded:
            logger.info("Tier 4: Rebuilding RemoteView database (same reload)...")
            rv_result = self._remote_view.rebuild()
            logger.info(
                f"Tier 4: RemoteView rebuilt - {rv_result.entity_count} entities, "
                f"{rv_result.resource_count} resources"
            )
