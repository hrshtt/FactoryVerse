"""Tier 4: FactoryVerse Runtime.

Orchestrates agent modules: remote_view, reachable_view, embodied_actions, DuckDB.

Supports two execution modes:
- JUPYTER: Code runs in isolated Jupyter kernel with notebook logging
- INPROCESS: Code runs in same Python process (lightweight, no notebook)
"""

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Optional, Any, List, TYPE_CHECKING

from ..config import RuntimeConfig, RuntimeVariant, ExecutionMode, SessionMode
from ..status import Tier4Status, TierState, PrerequisiteResult
from .base import TierBase, Tier, TierInitializationError

if TYPE_CHECKING:
    from ..environment import Environment
    from FactoryVerse.infra.execution.base import ExecutionEnvironment
    from FactoryVerse.infra.session.file_manager import SessionConfig
    from FactoryVerse.game.scenarios.base import ScenarioAdapter

logger = logging.getLogger(__name__)


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
        self._embodied_actions: Optional[Any] = None
        self._placement_hints: Optional[Any] = None
        self._ghost_builder: Optional[Any] = None
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
    def placement_hints(self) -> Optional[Any]:
        """Get PlacementHints for spatial reasoning and connection solving."""
        return self._placement_hints

    @property
    def ghost_builder(self) -> Optional[Any]:
        """Get GhostBuilder for building ghost entities."""
        return self._ghost_builder

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

            # Load modules based on variant
            # Order matters: embodied_actions -> reachable_view -> ghost_builder (needs reachable_view)
            await self._load_embodied_actions()
            await self._load_reachable_view()
            await self._load_ghost_builder()
            await self._load_placement_hints()

            # Load EventStream for temporal perception (game events)
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

        # Step 1: Query Lua for existing agents (SSOT)
        game_agents = tier3.list_game_agents()
        existing = next(
            (a for a in game_agents if a.get("interface_name") == requested_id),
            None,
        )

        if existing:
            # Agent exists in Factorio - check if we can bind or need to recreate
            existing_port = existing.get("udp_port")
            entity_valid = existing.get("entity_valid", True)

            if entity_valid and existing_port == udp_port:
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
        self._research = ResearchAction(rcon_handler)

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

    async def _load_ghost_builder(self) -> None:
        """Load GhostBuilder module for building ghost entities."""
        from FactoryVerse.game.agent.ghost_builder import GhostBuilderAction

        self._ghost_builder = GhostBuilderAction(
            movement=self._movement,
            placement=self._placement,
            inventory=self._inventory,
            reachable_view=self._reachable_view,
        )
        self._modules_loaded.append("ghost_builder")

        logger.info("Tier 4: GhostBuilder loaded")

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

    async def _load_placement_hints(self) -> None:
        """Load PlacementHints module (spatial reasoning for entity placement)."""
        from FactoryVerse.game.agent.placement_hints import PlacementHints

        tier3 = self._env.tier3
        if tier3 is None or tier3.rcon_helper is None:
            raise RuntimeError("Tier 3 must be initialized with RCON")

        # Use RconHandler for placement hints
        from FactoryVerse.game.agent.infra.rcon_handler import RconHandler

        rcon_handler = RconHandler(tier3.rcon_helper.rcon_client, self.agent_id)
        self._placement_hints = PlacementHints(rcon_handler)
        self._modules_loaded.append("placement_hints")

        logger.info("Tier 4: PlacementHints loaded")

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

                if system_phase == "MAINTENANCE":
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
        from FactoryVerse.infra.udp_dispatcher import UDPDispatcher

        tier3 = self._env.tier3
        if tier3 is None:
            raise RuntimeError("Tier 3 must be initialized")
        infra_config = self._env.config.infra_config
        if tier3 is None or tier3.instance is None:
            raise RuntimeError("Tier 3 must be initialized with instance")
        snapshot_dir = infra_config.get_snapshot_dir(tier3.instance)

        # RemoteView uses the global UDP dispatcher (get_udp_dispatcher) internally
        # for snapshot sync. That dispatcher binds to the snapshot port (34500 for client).
        # We don't create a separate one here to avoid port conflicts.
        #
        # The global dispatcher is started by RemoteView._wait_for_bootstrap_complete()
        # during load(), so we just pass None and let it use the global one.
        snapshot_udp_port = infra_config.get_snapshot_port(tier3.instance)
        logger.info(f"Tier 4: RemoteView will use snapshot port {snapshot_udp_port}")

        self._remote_view = RemoteView(
            snapshot_dir=snapshot_dir,
            entity_ops=self._entity_ops,
            place_ops=self._placement,
            walking_action=self._movement,
            mining_action=self._mining,
            udp_dispatcher=None,  # Let RemoteView use global dispatcher
            rcon_client=tier3._rcon,
        )

        # Load initial data and start sync service
        # Note: load() will start the global UDP dispatcher internally
        logger.info("Tier 4: Loading RemoteView data...")
        await self._remote_view.load(wait_for_bootstrap=True, bootstrap_timeout=120.0)
        await self._remote_view.start()  # Start real-time sync via UDP
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

        # Clear module references
        self._remote_view = None
        self._reachable_view = None
        self._embodied_actions = None
        self._placement_hints = None
        self._ghost_builder = None
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

    async def execute_code(self, code: str, compress_output: bool = False) -> str:
        """Execute Python code using in-process execution with notebook logging.

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

        # Placement planning types
        from FactoryVerse.game.agent.placement_hints import (
            ConnectionType,
            ConnectionPosition,
            WireConnectionPosition,
            GhostPlan,
            PolePlacementResult,
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
            # Placement planning types (ConnectionType, GhostPlan, etc.)
            # =================================================================
            "ConnectionType": ConnectionType,
            "ConnectionPosition": ConnectionPosition,
            "WireConnectionPosition": WireConnectionPosition,
            "GhostPlan": GhostPlan,
            "PolePlacementResult": PolePlacementResult,
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
            # Tier 3 components
            # =================================================================
            "rcon_client": tier3.rcon if tier3 else None,
            "runtime": runtime_proxy,  # For notification access
            # =================================================================
            # Tier 4 components (action modules and views)
            # =================================================================
            "agent_id": self._agent_id,
            "walking": self._movement,
            "crafting": self._crafting,
            "mining": self._mining,
            "research": self._research,
            "inventory": self._inventory,
            "placement": self._placement,
            "entity_ops": self._entity_ops,
            "reachable_view": self._reachable_view,
            "resources": self._reachable_view,  # Alias
            "remote_view": self._remote_view,
            "ghost_builder": self._ghost_builder,
            "placement_hints": self._placement_hints,
            # =================================================================
            # Scenario adapter (if detected)
            # =================================================================
            "scenario": self._scenario_adapter,
            # =================================================================
            # EventStream (temporal perception of game events)
            # =================================================================
            "events": self._event_stream,
        }
        namespace.update(builtin_names)

        # Capture stdout
        stdout_capture = io.StringIO()
        old_stdout = sys.stdout
        start_time = time.time()
        error_text = None

        try:
            sys.stdout = stdout_capture

            # Check if code contains 'await' - needs async execution
            if "await " in code:
                # Wrap code in async function that returns its locals
                indented_code = "\n".join(f"    {line}" for line in code.split("\n"))
                async_wrapper = f"async def __async_exec__():\n{indented_code}\n    return locals()\n"

                # Compile and execute the wrapper definition
                exec(compile(async_wrapper, "<string>", "exec"), namespace)

                # Await the async function and capture its local variables
                async_locals = await namespace["__async_exec__"]()

                # Merge async locals back into namespace (excluding internals)
                for k, v in async_locals.items():
                    if not k.startswith("_"):
                        namespace[k] = v
            else:
                # Sync code - simple exec
                exec(code, namespace)

            # Persist user-defined variables for next code block
            for k, v in namespace.items():
                if k not in builtin_names and not k.startswith("_"):
                    self._user_namespace[k] = v

            output = stdout_capture.getvalue().strip()

        except Exception as e:
            output = stdout_capture.getvalue().strip()
            error_text = f"Error: {type(e).__name__}: {e}"
            if output:
                output = f"{output}\n{error_text}"
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
        await self._load_placement_hints()
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
