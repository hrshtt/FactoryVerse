"""Orchestrator - Cross-tier patterns for Environment.

The Orchestrator provides high-level patterns that compose multiple tiers:
- run_task: Run a task with verification
- run_freeplay: Run open-ended exploration
- run_batch: Run multiple jobs on available cells

Interfaces (CLI, GUI, MCP) can:
- Call tier methods directly for low-level operations
- Use Orchestrator for cross-tier patterns

Example:
    >>> # Direct tier access for infrastructure
    >>> await env.tier1.start_client(scenario="test-ground")
    >>>
    >>> # Orchestrator for cross-tier patterns
    >>> result = await env.orchestrator.run_task(
    ...     task="iron_plate_throughput",
    ...     model="claude-3-opus",
    ... )
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any, TYPE_CHECKING, Callable, Awaitable

if TYPE_CHECKING:
    from .environment import Environment
    from .tiers.base import Tier
    from FactoryVerse.game.tasks.base import TaskConfig, VerificationResult
    from FactoryVerse.game.tasks.verification import ThroughputVerifier

logger = logging.getLogger(__name__)


# =============================================================================
# Result Types
# =============================================================================


@dataclass
class TaskResult:
    """Result of a single task run."""

    task_key: str
    model: str
    cell_index: Optional[int] = None

    # Interaction stats
    total_turns: int = 0
    total_tokens: int = 0
    total_actions: int = 0

    # Verification (None for freeplay)
    verification: Optional["VerificationResult"] = None

    # Timing
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None

    # Error handling
    success: bool = True
    error: Optional[str] = None
    error_turn: Optional[int] = None

    # Trajectory path
    trajectory_path: Optional[str] = None

    @property
    def duration_seconds(self) -> float:
        if self.started_at and self.ended_at:
            return (self.ended_at - self.started_at).total_seconds()
        return 0.0

    @property
    def task_success(self) -> bool:
        if self.verification is None:
            return self.success
        return self.verification.success and self.success

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_key": self.task_key,
            "model": self.model,
            "cell_index": self.cell_index,
            "total_turns": self.total_turns,
            "total_tokens": self.total_tokens,
            "total_actions": self.total_actions,
            "verification": self.verification.to_dict() if self.verification else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "duration_seconds": self.duration_seconds,
            "success": self.success,
            "task_success": self.task_success,
            "error": self.error,
            "error_turn": self.error_turn,
            "trajectory_path": self.trajectory_path,
        }


@dataclass
class FreeplayResult:
    """Result of a freeplay run."""

    model: str
    cell_index: Optional[int] = None

    # Interaction stats
    total_turns: int = 0
    total_tokens: int = 0
    total_actions: int = 0

    # Production stats
    items_produced: Dict[str, int] = field(default_factory=dict)
    entities_placed: int = 0
    technologies_researched: List[str] = field(default_factory=list)

    # Timing
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None

    # Error handling
    success: bool = True
    error: Optional[str] = None

    # Trajectory path
    trajectory_path: Optional[str] = None

    @property
    def duration_seconds(self) -> float:
        if self.started_at and self.ended_at:
            return (self.ended_at - self.started_at).total_seconds()
        return 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model": self.model,
            "cell_index": self.cell_index,
            "total_turns": self.total_turns,
            "total_tokens": self.total_tokens,
            "total_actions": self.total_actions,
            "items_produced": self.items_produced,
            "entities_placed": self.entities_placed,
            "technologies_researched": self.technologies_researched,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "duration_seconds": self.duration_seconds,
            "success": self.success,
            "error": self.error,
            "trajectory_path": self.trajectory_path,
        }


@dataclass
class Job:
    """A single job in a batch run."""

    task_key: str
    model: str
    trial: int = 0
    cell_index: Optional[int] = None

    @property
    def job_id(self) -> str:
        return f"{self.task_key}:{self.model}:trial{self.trial}"


@dataclass
class BatchResult:
    """Result of a batch of jobs."""

    total_jobs: int = 0
    completed_jobs: int = 0
    successful_jobs: int = 0
    failed_jobs: int = 0

    results: List[TaskResult] = field(default_factory=list)

    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None

    @property
    def success_rate(self) -> float:
        if self.completed_jobs == 0:
            return 0.0
        return self.successful_jobs / self.completed_jobs

    @property
    def duration_seconds(self) -> float:
        if self.started_at and self.ended_at:
            return (self.ended_at - self.started_at).total_seconds()
        return 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_jobs": self.total_jobs,
            "completed_jobs": self.completed_jobs,
            "successful_jobs": self.successful_jobs,
            "failed_jobs": self.failed_jobs,
            "success_rate": self.success_rate,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "duration_seconds": self.duration_seconds,
            "results": [r.to_dict() for r in self.results],
        }


# =============================================================================
# Orchestrator
# =============================================================================


class Orchestrator:
    """Cross-tier orchestration patterns.

    Provides high-level methods that compose multiple tiers:
    - run_task: Initialize → inject task → run agent → verify
    - run_freeplay: Initialize → run agent
    - run_batch: Allocate cells → run jobs concurrently

    For low-level operations (start client, connect, etc.),
    interfaces should call tier methods directly.
    """

    def __init__(self, env: "Environment"):
        self._env = env
        self._active_cells: set[int] = set()

    # =========================================================================
    # Infrastructure Patterns (cross-tier)
    # =========================================================================

    async def connect_and_verify(
        self,
        instance: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Connect to instance and verify game state.

        Composes: instance detection → tier 3 connect → query game state

        Args:
            instance: Instance name, or None to auto-detect

        Returns:
            Dict with instance info, game tick, agents
        """
        from .tiers.base import Tier
        from .config import InfraMode
        from FactoryVerse.infra.instance_manager import FactorioInstanceManager

        # Auto-detect if not specified
        if instance is None:
            detected = FactorioInstanceManager.detect_active()
            if detected is None:
                return {
                    "success": False,
                    "error": "No active Factorio instance found",
                }
            instance = detected.name
            logger.info(f"Orchestrator: Auto-detected instance '{instance}'")

        # Configure for external connection
        self._env.config.tier1.mode = InfraMode.EXTERNAL
        self._env.config.tier3.instance = instance

        # Initialize up to tier 3
        try:
            await self._ensure_ready(up_to=Tier.PYTHON_INFRA)
        except Exception as e:
            return {"success": False, "error": str(e)}

        tier3 = self._env.tier3
        if tier3 is None:
            return {"success": False, "error": "Failed to initialize tier 3"}

        # Query game state
        try:
            game_tick = tier3.get_game_tick()
            agents = tier3.list_game_agents()

            return {
                "success": True,
                "instance": instance,
                "game_tick": game_tick,
                "agents": agents,
                "agent_count": len(agents),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def prepare_for_evaluation(
        self,
        scenario: str = "lab-grid",
        provider: str = "anthropic",
        model: str = "claude-sonnet-4-20250514",
    ) -> Dict[str, Any]:
        """Prepare environment for task evaluation.

        Composes: connect → configure → initialize all tiers → verify ready

        Args:
            scenario: Scenario to use
            provider: LLM provider
            model: Model to use

        Returns:
            Dict with readiness status and available cells
        """
        from .tiers.base import Tier

        # Configure environment
        self._env.config.tier2.scenario = scenario
        self._env.config.tier6.llm_provider = provider
        self._env.config.tier6.model = model

        try:
            # Initialize all tiers
            await self._ensure_ready(up_to=Tier.INTERACTION)

            # Get available cells
            cells = self._get_available_cells()

            tier4 = self._env.tier4
            tier6 = self._env.tier6

            return {
                "success": True,
                "scenario": scenario,
                "provider": provider,
                "model": model,
                "available_cells": cells,
                "cell_count": len(cells),
                "session_dir": str(tier4.session_dir) if tier4 and tier4.session_dir else None,
                "tools_registered": tier6._tools_registered if tier6 else 0,
            }

        except Exception as e:
            logger.exception("Orchestrator: Failed to prepare for evaluation")
            return {"success": False, "error": str(e)}

    async def get_full_status(self) -> Dict[str, Any]:
        """Get comprehensive status across all tiers.

        Composes: query each initialized tier for status

        Returns:
            Dict with tier statuses, instance info, game state
        """
        from FactoryVerse.infra.instance_manager import FactorioInstanceManager

        status: Dict[str, Any] = {
            "initialized_up_to": self._env._initialized_up_to.name if self._env._initialized_up_to else None,
            "tiers": {},
            "instances": [],
        }

        # List all instances
        for inst in FactorioInstanceManager.list_available():
            status["instances"].append({
                "name": inst.name,
                "rcon_port": inst.rcon_port,
                "active": inst.test_connection(),
            })

        # Query each tier
        if self._env._tier1:
            tier1_status = await self._env._tier1.verify_ready()
            status["tiers"]["tier1"] = {
                "ready": tier1_status.is_ready,
                "details": tier1_status.details,
            }

        if self._env._tier2:
            tier2_status = await self._env._tier2.verify_ready()
            status["tiers"]["tier2"] = {
                "ready": tier2_status.is_ready,
                "scenario": self._env.config.tier2.scenario,
            }

        if self._env._tier3:
            tier3_status = await self._env._tier3.verify_ready()
            status["tiers"]["tier3"] = {
                "ready": tier3_status.is_ready,
                "instance": self._env.config.tier3.instance,
            }
            # Add game state if connected
            if tier3_status.is_ready:
                try:
                    status["game_tick"] = self._env._tier3.get_game_tick()
                    status["agents"] = self._env._tier3.list_game_agents()
                except Exception:
                    pass

        if self._env._tier4:
            tier4_status = await self._env._tier4.verify_ready()
            status["tiers"]["tier4"] = {
                "ready": tier4_status.is_ready,
                "modules": list(self._env._tier4._modules_loaded) if hasattr(self._env._tier4, '_modules_loaded') else [],
            }
            # Add available cells
            status["available_cells"] = self._get_available_cells()

        if self._env._tier5:
            tier5_status = await self._env._tier5.verify_ready()
            status["tiers"]["tier5"] = {
                "ready": tier5_status.is_ready,
                "task": self._env.config.tier5.task_name,
            }

        if self._env._tier6:
            tier6_status = await self._env._tier6.verify_ready()
            status["tiers"]["tier6"] = {
                "ready": tier6_status.is_ready,
                "provider": self._env.config.tier6.llm_provider,
                "model": self._env.config.tier6.model,
            }

        return status

    # =========================================================================
    # Agent Patterns (cross-tier)
    # =========================================================================

    async def run_task(
        self,
        task: str,
        model: str,
        cell: Optional[int] = None,
        max_turns: Optional[int] = None,
        provider: Optional[str] = None,
    ) -> TaskResult:
        """Run a task evaluation with verification.

        Composes: tier initialization → task injection → agent loop → verification

        Args:
            task: Task key (e.g., "iron_plate_throughput")
            model: Model name
            cell: Specific cell index, or None to auto-allocate
            max_turns: Maximum turns, or None to use task default
            provider: LLM provider, or None to use config default

        Returns:
            TaskResult with verification, stats, and any errors
        """
        from .tiers.base import Tier
        from FactoryVerse.game.tasks.registry import TaskRegistry

        result = TaskResult(
            task_key=task,
            model=model,
            started_at=datetime.now(),
        )

        allocated_cell = None

        try:
            # Load task config
            registry = TaskRegistry.get()
            if not registry.task_exists(task):
                result.success = False
                result.error = f"Task '{task}' not found in registry"
                result.ended_at = datetime.now()
                return result

            task_config = registry.get_task(task)
            effective_max_turns = max_turns or task_config.max_trajectory_steps

            # Configure environment for this run
            self._configure_for_task(task, model, provider, effective_max_turns)

            # Ensure environment is ready
            await self._ensure_ready(up_to=Tier.INTERACTION)

            # Allocate cell if using lab-grid (includes reset + agent creation)
            allocated_cell = await self._allocate_cell(
                cell,
                starting_inventory=task_config.starting_inventory,
            )
            if allocated_cell is not None:
                result.cell_index = allocated_cell

            # Run interaction loop
            tier6 = self._env.tier6
            if tier6 is None:
                raise RuntimeError("Tier 6 not initialized")

            # Configure automatic task verification
            # Creates a callback that runs verification after each tool call
            if task_config.verification is not None:
                verification_callback = self._create_verification_callback(task_config)
                tier6.configure_task_verification(task_config, verification_callback)
                logger.info(
                    f"Orchestrator: Task verification enabled for '{task}' "
                    f"(target: {task_config.verification.target_item}, "
                    f"quota: {task_config.verification.quota}/60s)"
                )

            logger.info(
                f"Orchestrator: Starting task '{task}' with model '{model}' "
                f"(max_turns={effective_max_turns})"
            )

            initial_message = f"Your task: {task_config.goal_description}\n\nBegin."
            await tier6.run_loop(initial_message=initial_message)

            # Collect stats
            stats = tier6.get_statistics()
            result.total_turns = stats.get("total_turns", 0)
            result.total_actions = stats.get("total_actions", 0)

            # Get trajectory path
            tier4 = self._env.tier4
            if tier4 and tier4.session_dir:
                result.trajectory_path = str(tier4.session_dir / "trajectory.jsonl")

            # Verify task completion
            result.verification = await self._verify_task(task_config)

            logger.info(
                f"Orchestrator: Task '{task}' completed. "
                f"Verification: {result.verification.success if result.verification else 'N/A'}"
            )

        except Exception as e:
            logger.exception(f"Orchestrator: Error running task '{task}'")
            result.success = False
            result.error = str(e)

        finally:
            result.ended_at = datetime.now()
            if allocated_cell is not None:
                await self._release_cell(allocated_cell, reset=True)

        return result

    async def run_freeplay(
        self,
        model: str,
        max_turns: int = 200,
        cell: Optional[int] = None,
        provider: Optional[str] = None,
        initial_message: Optional[str] = None,
    ) -> FreeplayResult:
        """Run open-ended freeplay.

        Composes: tier initialization → agent loop (no verification)

        Args:
            model: Model name
            max_turns: Maximum turns
            cell: Specific cell index, or None to auto-allocate
            provider: LLM provider
            initial_message: Custom initial message

        Returns:
            FreeplayResult with production stats
        """
        from .tiers.base import Tier

        result = FreeplayResult(
            model=model,
            started_at=datetime.now(),
        )

        allocated_cell = None

        try:
            self._configure_for_freeplay(model, provider, max_turns)
            await self._ensure_ready(up_to=Tier.INTERACTION)

            # Use default freeplay inventory (can be customized)
            from FactoryVerse.game.tasks.definitions.common import LAB_STARTING_INVENTORY

            allocated_cell = await self._allocate_cell(
                cell,
                starting_inventory=LAB_STARTING_INVENTORY,
            )
            if allocated_cell is not None:
                result.cell_index = allocated_cell

            tier6 = self._env.tier6
            if tier6 is None:
                raise RuntimeError("Tier 6 not initialized")

            message = initial_message or (
                "You are in freeplay mode. Build whatever factory you want! "
                "Explore, experiment, and have fun automating production."
            )

            await tier6.run_loop(initial_message=message)

            stats = tier6.get_statistics()
            result.total_turns = stats.get("total_turns", 0)
            result.total_actions = stats.get("total_actions", 0)

            tier4 = self._env.tier4
            if tier4 and tier4.session_dir:
                result.trajectory_path = str(tier4.session_dir / "trajectory.jsonl")

        except Exception as e:
            logger.exception("Orchestrator: Error in freeplay")
            result.success = False
            result.error = str(e)

        finally:
            result.ended_at = datetime.now()
            if allocated_cell is not None:
                await self._release_cell(allocated_cell, reset=True)

        return result

    async def run_batch(
        self,
        jobs: List[Job],
        max_concurrent: int = 8,
    ) -> BatchResult:
        """Run multiple jobs using available cells.

        Args:
            jobs: List of jobs to run
            max_concurrent: Maximum concurrent jobs

        Returns:
            BatchResult with individual results and summary
        """
        result = BatchResult(
            total_jobs=len(jobs),
            started_at=datetime.now(),
        )

        available_cells = self._get_available_cells()
        effective_concurrency = min(max_concurrent, len(available_cells))

        if effective_concurrency == 0:
            logger.warning("Orchestrator: No cells available for batch")
            result.ended_at = datetime.now()
            return result

        logger.info(
            f"Orchestrator: Running batch of {len(jobs)} jobs "
            f"with concurrency {effective_concurrency}"
        )

        semaphore = asyncio.Semaphore(effective_concurrency)

        async def run_job_with_semaphore(job: Job) -> TaskResult:
            async with semaphore:
                return await self.run_task(
                    task=job.task_key,
                    model=job.model,
                    cell=job.cell_index,
                )

        tasks = [run_job_with_semaphore(job) for job in jobs]
        job_results = await asyncio.gather(*tasks, return_exceptions=True)

        for job_result in job_results:
            if isinstance(job_result, Exception):
                result.failed_jobs += 1
                failed_result = TaskResult(
                    task_key="unknown",
                    model="unknown",
                    success=False,
                    error=str(job_result),
                )
                result.results.append(failed_result)
            else:
                result.results.append(job_result)
                result.completed_jobs += 1
                if job_result.task_success:
                    result.successful_jobs += 1
                else:
                    result.failed_jobs += 1

        result.ended_at = datetime.now()

        logger.info(
            f"Orchestrator: Batch complete. "
            f"{result.successful_jobs}/{result.total_jobs} successful "
            f"({result.success_rate:.1%})"
        )

        return result

    # =========================================================================
    # Private Helpers
    # =========================================================================

    async def _ensure_ready(self, up_to: "Tier") -> None:
        """Ensure environment is initialized to required tier."""
        current = self._env._initialized_up_to
        if current is None or current < up_to:
            logger.info(f"Orchestrator: Initializing environment to {up_to.name}")
            await self._env.initialize(up_to=up_to)

    def _get_available_cells(self) -> List[int]:
        """Get cells not currently in use."""
        tier4 = self._env.tier4
        if tier4 is None or tier4.scenario is None:
            return [0] if 0 not in self._active_cells else []

        try:
            all_empty = tier4.scenario.get_empty_cells()
            return [c for c in all_empty if c not in self._active_cells]
        except Exception:
            return []

    def _configure_for_task(
        self,
        task: str,
        model: str,
        provider: Optional[str],
        max_turns: int,
    ) -> None:
        """Configure environment for a task run."""
        from .config import InteractionMode

        config = self._env.config
        config.tier5.task_name = task
        config.tier6.model = model
        config.tier6.mode = InteractionMode.AUTONOMOUS
        config.tier6.max_turns = max_turns
        if provider:
            config.tier6.llm_provider = provider

    def _configure_for_freeplay(
        self,
        model: str,
        provider: Optional[str],
        max_turns: int,
    ) -> None:
        """Configure environment for freeplay."""
        from .config import InteractionMode

        config = self._env.config
        config.tier5.task_name = None
        config.tier6.model = model
        config.tier6.mode = InteractionMode.AUTONOMOUS
        config.tier6.max_turns = max_turns
        if provider:
            config.tier6.llm_provider = provider

    async def _allocate_cell(
        self,
        requested: Optional[int],
        starting_inventory: Optional[Dict[str, int]] = None,
    ) -> Optional[int]:
        """Allocate and set up a cell for this run.

        Delegates to the scenario adapter's allocate_cell() method which handles:
        1. Cell selection/validation
        2. Reset (spawns resources, triggers snapshot)
        3. Agent validation/recreation
        4. Agent assignment and teleportation
        5. Snapshot coordination
        6. Inventory setup
        """
        tier4 = self._env.tier4
        if tier4 is None or tier4.scenario is None:
            return None

        scenario = tier4.scenario

        # Validate cell not already in use
        if requested is not None and requested in self._active_cells:
            raise RuntimeError(f"Cell {requested} is already in use")

        # Get agent numeric ID
        agent_id_str = tier4.config.agent_id or "agent_1"
        try:
            agent_numeric_id = int(agent_id_str.split("_")[1])
        except (IndexError, ValueError):
            agent_numeric_id = 1

        # Delegate to adapter's orchestration method
        result = await scenario.allocate_cell(
            cell_index=requested,
            agent_id=agent_numeric_id,
            starting_inventory=starting_inventory,
            wait_for_snapshot=True,
            snapshot_timeout=60.0,
        )

        if not result.success:
            raise RuntimeError(result.error or "Cell allocation failed")

        self._active_cells.add(result.cell_index)
        logger.info(
            f"Orchestrator: Allocated cell {result.cell_index} "
            f"(snapshot: {result.snapshot_complete}, chunks: {result.chunks_snapshotted})"
        )

        # CRITICAL: Reload DuckDB after cell allocation triggers snapshot
        # With DEFERRED/SELECTIVE snapshotting (lab-grid), the initial bootstrap
        # completes with 0 chunks because nothing is triggered until allocate_cell.
        # We need to reload the database now that snapshot files have been written.
        if result.snapshot_complete and tier4 is not None:
            logger.info("Orchestrator: Reloading snapshot data after cell allocation...")
            tier4.reload_snapshot_data()
            logger.info("Orchestrator: Snapshot data reloaded")

        return result.cell_index

    async def _release_cell(self, cell: int, reset: bool = True) -> None:
        """Release a cell back to the pool."""
        self._active_cells.discard(cell)

        tier4 = self._env.tier4
        if tier4 and tier4.scenario:
            try:
                await tier4.scenario.release_cell(cell, reset=reset)
                logger.debug(f"Orchestrator: Released cell {cell}")
            except Exception as e:
                logger.warning(f"Orchestrator: Failed to release cell {cell}: {e}")

    def _create_verification_callback(
        self, task_config: "TaskConfig"
    ) -> Callable[[], Awaitable[Optional["VerificationResult"]]]:
        """Create a verification callback for automatic task checking.

        For THROUGHPUT tasks, creates a ThroughputVerifier that maintains
        state across calls to track sustained production rate.

        The callback captures the current environment state and task config,
        then returns a verification function that can be called after each tool call.

        Args:
            task_config: Task configuration with verification criteria

        Returns:
            Async callback that performs verification
        """
        from FactoryVerse.game.tasks.base import TaskType
        from FactoryVerse.game.tasks.verification import ThroughputVerifier

        # Create verifier for throughput tasks (maintains state across checks)
        verifier = None
        if task_config.task_type == TaskType.THROUGHPUT and task_config.verification:
            verifier = ThroughputVerifier(task_config.verification)
            logger.info(
                f"Orchestrator: Created ThroughputVerifier for {task_config.task_key} "
                f"(quota={task_config.verification.quota}/60s, "
                f"sustained={task_config.verification.sustained_seconds}s)"
            )

        async def verify() -> Optional["VerificationResult"]:
            return await self._verify_task(task_config, verifier)

        return verify

    async def _verify_task(
        self,
        task_config: "TaskConfig",
        verifier: Optional["ThroughputVerifier"] = None,
    ) -> Optional["VerificationResult"]:
        """Verify task completion.

        Uses file-based statistics from fv_snapshot:
        - production-statistics.jsonl (force-level, written on change)
        - crafting-statistics.jsonl (manual crafting, event-driven)
        - mining-statistics.jsonl (manual mining, event-driven)

        Args:
            task_config: Task configuration with verification criteria
            verifier: Optional ThroughputVerifier for rate-based tasks

        Returns:
            VerificationResult or None if task type doesn't require verification
        """
        from FactoryVerse.game.tasks.base import TaskType
        from FactoryVerse.game.tasks.verification import verify_task, ThroughputVerifier
        from FactoryVerse.game.tasks.sources import AgentSnapshotSource

        if task_config.task_type == TaskType.FREEPLAY:
            return None

        if task_config.verification is None:
            return None

        tier3 = self._env.tier3
        tier4 = self._env.tier4

        if tier3 is None:
            logger.warning("Orchestrator: Cannot verify - tier3 not initialized")
            return None

        # Get script-output directory for file-based statistics
        # NOTE: AgentSnapshotSource expects the BASE script-output directory,
        # NOT get_snapshot_dir() which returns script-output/factoryverse/snapshots
        infra_config = self._env.config.infra_config
        script_output_dir = infra_config.get_script_output_dir(tier3.instance)

        # Use file-based source instead of RCON polling
        source = AgentSnapshotSource(script_output_dir)

        agent_id = 1
        if tier4 and tier4.agent_id:
            try:
                agent_id = int(tier4.agent_id.split("_")[1])
            except (ValueError, IndexError):
                pass

        return await verify_task(task_config, source, agent_id, verifier=verifier)
