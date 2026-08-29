"""Tier 6: Generative/Interactive Layer.

Orchestrates LLM connection and agent turn loop.
"""

import logging
from typing import Optional, Any, Dict, List, TYPE_CHECKING, Callable, Awaitable

from ..config import InteractionConfig, InteractionMode
from ..status import Tier6Status, TierState, PrerequisiteResult
from ..tool_definitions import (
    check_read_only,
    get_tool_definitions as _shared_tool_definitions,
    leading_keyword,
)
from ..config import TurnConfig
from .base import TierBase, Tier, TierInitializationError

if TYPE_CHECKING:
    from ..environment import Environment
    from FactoryVerse.game.tasks.base import TaskConfig, VerificationResult

logger = logging.getLogger(__name__)

# Type alias for verification callback
VerificationCallback = Callable[[], Awaitable[Optional["VerificationResult"]]]


class Tier6Interaction(TierBase):
    """Tier 6: Generative/Interactive Layer.

    Manages LLM interaction in three modes:
    - AUTONOMOUS: Continuous agent loop with context management
    - ASSISTED: Single-turn interaction per user message
    - MCP: MCP server mode where context is managed externally
    """

    tier_level = Tier.INTERACTION

    def __init__(self, environment: "Environment"):
        super().__init__(environment)
        self._llm_client: Optional[Any] = None
        self._orchestrator: Optional[Any] = None
        self._trajectory_writer: Optional[Any] = None
        self._console_output: Optional[Any] = None
        self._tools_registered: int = 0

    @property
    def config(self) -> InteractionConfig:
        """Get tier 6 configuration."""
        return self._env.config.tier6

    @property
    def llm_client(self) -> Optional[Any]:
        """Get LLM client."""
        return self._llm_client

    @property
    def orchestrator(self) -> Optional[Any]:
        """Get AgentOrchestrator."""
        return self._orchestrator

    async def verify_prerequisites(self) -> PrerequisiteResult:
        """Verify Tier 5 (Specification) is ready."""
        tier5 = self._env.tier5

        if tier5 is None or not tier5.is_ready:
            return PrerequisiteResult.failed(
                missing=["tier5_specification"],
                message="Agent specification must be ready before interaction",
            )

        return PrerequisiteResult.ok()

    async def initialize(self) -> None:
        """Initialize LLM client and orchestrator."""
        self._set_state(TierState.INITIALIZING)

        try:
            # Initialize LLM client
            await self._init_llm_client()

            # Initialize trajectory writer
            await self._init_trajectory_writer()

            # Initialize console output (for streaming agent thoughts/actions)
            await self._init_console_output()

            # Initialize orchestrator
            await self._init_orchestrator()

            self._set_state(TierState.READY)

        except Exception as e:
            self._set_state(TierState.ERROR, str(e))
            raise TierInitializationError(self.tier_level, str(e)) from e

    async def _init_llm_client(self) -> None:
        """Initialize LLM client from config."""
        from FactoryVerse.infra.llm.client.factory import create_client_from_env

        self._llm_client = create_client_from_env(
            provider=self.config.llm_provider,
            model=self.config.model,
        )

        logger.info(
            f"Tier 6: LLM client initialized ({self.config.llm_provider}/{self.config.model})"
        )

    async def _init_trajectory_writer(self) -> None:
        """Get trajectory writer from Tier 4 and add LLM session metadata.

        Tier 4 owns the trajectory writer (source of truth for the run).
        Tier 6 adds LLM-specific events (model, provider, mode).
        """
        tier4 = self._env.tier4
        if tier4 and tier4.trajectory_writer:
            # Use Tier 4's trajectory writer
            self._trajectory_writer = tier4.trajectory_writer

            # Add LLM session start event with model/mode info
            self._trajectory_writer.session_start(
                model=self.config.model,
                mode=self.config.mode.value if hasattr(self.config.mode, 'value') else str(self.config.mode),
            )
            logger.info(
                f"Tier 6: Using Tier 4 trajectory writer, added LLM session start "
                f"({self.config.llm_provider}/{self.config.model})"
            )
        else:
            logger.warning("Tier 6: No trajectory writer available from Tier 4")

    async def _init_console_output(self) -> None:
        """Initialize console output for streaming agent thoughts/actions."""
        from FactoryVerse.infra.output.console import ConsoleOutput

        # Create ConsoleOutput based on config
        enabled = self.config.console_output_enabled
        self._console_output = ConsoleOutput(enabled=enabled)

        if enabled:
            logger.info("Tier 6: Console output enabled (streaming agent thoughts/actions)")
        else:
            logger.info("Tier 6: Console output disabled")

    async def _init_orchestrator(self) -> None:
        """Initialize AgentOrchestrator."""
        from FactoryVerse.infra.llm.orchestrator import AgentOrchestrator
        import tempfile

        tier5 = self._env.tier5
        if tier5 is None:
            raise RuntimeError("Tier 5 must be initialized")

        # Create a runtime protocol adapter
        runtime = self._create_runtime_adapter()

        # Get tool definitions
        mode = (
            "autonomous"
            if self.config.mode == InteractionMode.AUTONOMOUS
            else "assisted"
        )
        tool_defs = runtime.get_tool_definitions(mode=mode)
        self._tools_registered = len(tool_defs)

        # Get session paths from Tier 4
        tier4 = self._env.tier4
        chat_log_path = None
        system_prompt_path = None

        if tier4:
            # Use session directory paths if available
            if tier4.system_prompt_path:
                system_prompt_path = str(tier4.system_prompt_path)
            if tier4.chat_log_path:
                chat_log_path = str(tier4.chat_log_path)

        # Write system prompt to file (session-scoped or temp)
        system_prompt = tier5.system_prompt or "You are a Factorio automation agent."
        if system_prompt_path:
            # Write to session directory (persistent)
            with open(system_prompt_path, "w") as f:
                f.write(system_prompt)
            prompt_path = system_prompt_path
        else:
            # Fallback to temp file
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".md", delete=False
            ) as prompt_file:
                prompt_file.write(system_prompt)
                prompt_path = prompt_file.name

        if self._llm_client is None:
            raise RuntimeError("LLM Client not initialized")

        # The planning turn's plan helper lives in the session dir and is
        # bound into tier 4's namespace as `plan` (TURN_CONTRACT §6).
        from FactoryVerse.game.agent.turn_report import PlanStore

        plan_path = (tier4.session_dir / "plan.json") if tier4 and tier4.session_dir else None
        plan_store = PlanStore(plan_path)
        if tier4 and hasattr(tier4, "set_plan_store"):
            tier4.set_plan_store(plan_store)
        runtime.plan_store = plan_store

        self._orchestrator = AgentOrchestrator(
            llm_client=self._llm_client,
            runtime=runtime,
            system_prompt_path=prompt_path,
            chat_log_path=chat_log_path,
            console_output=self._console_output,
            trajectory_writer=self._trajectory_writer,
            max_context_tokens=self.config.max_context_tokens,
            mode=mode,
            initial_state_path=str(tier4.initial_state_path) if tier4 and tier4.initial_state_path else None,
            turn_config=self.config.turn,
        )
        if self._trajectory_writer is not None and hasattr(self._trajectory_writer, "_write"):
            # The constants are an experimental condition: on the record by hash.
            try:
                self._trajectory_writer._write(  # type: ignore[attr-defined]
                    "turn_config", turn=0, sha256=self.config.turn.sha256(), config=self.config.turn.model_dump()
                )
            except Exception as e:  # never kill a run over a record line
                logger.debug(f"turn_config record skipped: {e}")

        if self.config.max_turns:
            self._orchestrator.set_max_turns(self.config.max_turns)

        logger.info(
            f"Tier 6: Orchestrator initialized in {mode} mode with {self._tools_registered} tools"
        )

    def _create_runtime_adapter(self) -> Any:
        """Create runtime adapter that satisfies RuntimeProtocol."""
        tier3 = self._env.tier3
        tier4 = self._env.tier4

        # Return an adapter that wraps our tier components
        return _RuntimeAdapter(tier3=tier3, tier4=tier4)

    async def verify_ready(self) -> Tier6Status:
        """Verify interaction layer is ready."""
        if self._state != TierState.READY:
            return Tier6Status(
                state=self._state,
                error=self._error,
            )

        # Check LLM responsiveness
        llm_connected = self._llm_client is not None
        llm_responsive = False

        if llm_connected:
            try:
                # Simple ping - just check we can create a message
                llm_responsive = True
            except Exception:
                pass

        return Tier6Status(
            state=self._state,
            llm_connected=llm_connected,
            llm_responsive=llm_responsive,
            orchestrator_mode=self.config.mode.value
            if hasattr(self.config.mode, "value")
            else self.config.mode,
            tools_registered=self._tools_registered,
        )

    async def reset(self) -> None:
        """Reset by recreating orchestrator."""
        await self.shutdown()
        await self.initialize()

    async def shutdown(self) -> None:
        """Shutdown interaction layer."""
        self._set_state(TierState.SHUTTING_DOWN)

        self._orchestrator = None
        self._llm_client = None
        self._trajectory_writer = None
        self._console_output = None
        self._tools_registered = 0

        self._set_state(TierState.SHUTDOWN)

    # =========================================================================
    # Interaction Methods
    # =========================================================================

    async def run_turn(self, user_message: str) -> str:
        """Run single agent turn.

        Args:
            user_message: User message to process

        Returns:
            Agent's response
        """
        if not self._orchestrator:
            raise RuntimeError("Orchestrator not initialized")

        return await self._orchestrator.run_turn(user_message)

    async def run_loop(self, initial_message: Optional[str] = None) -> None:
        """Run autonomous agent loop.

        Args:
            initial_message: Optional initial message to start with
        """
        if not self._orchestrator:
            raise RuntimeError("Orchestrator not initialized")

        if self.config.mode != InteractionMode.AUTONOMOUS:
            raise RuntimeError("run_loop only available in AUTONOMOUS mode")

        # Initial message or default
        message = initial_message or "Begin your task."

        while self._orchestrator.has_turns_remaining():
            try:
                await self._orchestrator.run_turn(message)

                # From the second turn on, the turn report IS the message
                # (TURN_CONTRACT §21); the orchestrator prepends it itself.
                message = ""

            except Exception as e:
                # Do not swallow. Breaking here left the caller believing the
                # run ended normally, so a run that died on its second turn
                # still printed "Freeplay completed". A harness whose purpose
                # is to not lie must not report success on failure.
                logger.error(f"Tier 6: Error in agent loop: {e}", exc_info=True)
                raise

    async def start_session(self) -> str:
        """Start a new agent session.

        Returns:
            Session ID
        """
        tier4 = self._env.tier4
        return str(tier4.session_dir) if tier4 and tier4.session_dir else "unknown"

    def get_statistics(self) -> Dict[str, Any]:
        """Get trajectory statistics."""
        if self._orchestrator:
            return self._orchestrator.get_statistics()
        return {}

    def configure_task_verification(
        self,
        task_config: "TaskConfig",
        verification_callback: VerificationCallback,
    ) -> None:
        """Configure automatic task verification.

        This sets up the orchestrator to automatically verify task completion
        after each tool call. When verification passes, the loop exits.

        Args:
            task_config: Task configuration with verification criteria
            verification_callback: Async callback that returns VerificationResult
        """
        if not self._orchestrator:
            raise RuntimeError("Orchestrator not initialized")

        self._orchestrator.set_task_config(task_config)
        self._orchestrator.set_verification_callback(verification_callback)

        logger.info(
            f"Tier 6: Task verification configured for '{task_config.task_key}'"
        )


class _NoDatabase(Exception):
    """No queryable database is attached to this runtime."""


def _cell(value: Any) -> str:
    """Render one value for a text table without breaking the row."""
    if value is None:
        return "NULL"
    text = str(value)
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def _render_query_result(
    columns: Optional[List[str]],
    rows: List[List[Any]],
    total: int,
) -> str:
    """Render query rows as a pipe table with a row count and a cap notice.

    The shape is deliberate: ``Rows: N`` and the ``| --- |`` separator are what
    OutputCompressor.compress_query_result looks for, so the character cap
    downstream degrades this into "showing X of N rows" rather than a blind
    character chop.
    """
    if total == 0:
        header = "Rows: 0 (no rows matched)"
        if columns:
            header += "\nColumns: " + ", ".join(columns)
        return header

    lines = [f"Rows: {total}"]
    if columns is None:
        lines.append(
            "(column names unavailable for this statement type — values in "
            "statement order)"
        )
        width = max((len(r) for r in rows), default=0)
        columns = [f"col{i + 1}" for i in range(width)]

    lines.append("| " + " | ".join(_cell(c) for c in columns) + " |")
    lines.append("| " + " | ".join("---" for _ in columns) + " |")
    for row in rows:
        lines.append("| " + " | ".join(_cell(v) for v in row) + " |")

    if total > len(rows):
        lines.append(
            f"\n[showing first {len(rows)} of {total} rows — {total - len(rows)} "
            f"not shown; narrow or aggregate the query to see the rest]"
        )

    return "\n".join(lines)


class _RuntimeAdapter:
    """Adapter that implements RuntimeProtocol using Environment tiers.

    Provides the runtime interface expected by AgentOrchestrator:
    - execute_code: Run Python code with access to embodied actions
    - execute_dsl: Run Lua code via RCON
    - execute_duckdb: Query the game state database
    - events: EventStream for temporal perception (preferred)
    - _listener: Access to AsyncActionListener (legacy, for backwards compat)
    """

    # Caps for the query tool. Rows are capped while fetching so a huge
    # result is never materialised into a string; the compressor then
    # enforces the character cap.
    _DUCKDB_MAX_ROWS = 100
    _DUCKDB_MAX_CHARS = 5000

    def __init__(self, tier3, tier4):
        self._tier3 = tier3
        self._tier4 = tier4
        # Tick span of the most recent tool call: {"before", "after"} or None.
        # The orchestrator copies it onto the tool_result record.
        self.last_tick_span: Optional[Dict[str, int]] = None
        # TURN_CONTRACT §6: which namespace execute_dsl binds this turn.
        self.turn_mode: str = "gameplay"
        self.plan_store: Any = None
        self._status_reader: Any = None
        self._energy_cache: Dict[str, Optional[float]] = {}

    # ------------------------------------------------------------------
    # Turn contract (TURN_CONTRACT §3–§5): the reads the report is made of
    # ------------------------------------------------------------------

    def advance_world(self, ticks: int):
        """Fast-forward by exactly ``ticks``; returns a ``WorldAdvance`` (count
        plus the paused start/end ticks) or None when there is no engine."""
        if not self._tier3 or ticks <= 0:
            return None
        return self._tier3.advance_world(ticks)

    def advance_world_to(self, target_tick: int):
        """Pause, then advance to exactly ``target_tick``; None without an engine."""
        if not self._tier3:
            return None
        return self._tier3.advance_world_to(target_tick)

    def _agent_interface(self) -> Optional[str]:
        return getattr(self._tier4, "agent_id", None) if self._tier4 else None

    def _lua(self, code: str) -> Any:
        if not self._tier3:
            return None
        try:
            return self._tier3.run_lua(code)
        except Exception as e:
            logger.debug(f"turn read failed ({code[:60]}): {e}")
            return None

    def production_statistics(self) -> Dict[str, Dict[str, int]]:
        """Force item production statistics — `input`/`output` counts (live)."""
        iface = self._agent_interface()
        if not iface:
            return {"input": {}, "output": {}}
        data = self._lua(f"return remote.call('{iface}', 'get_production_statistics')") or {}
        return {
            "input": dict(data.get("input") or {}),
            "output": dict(data.get("output") or {}),
        }

    def researched_count(self) -> int:
        """Number of researched technologies on the agent's force (live)."""
        iface = self._agent_interface()
        if not iface:
            return 0
        n = self._lua(
            "local agents = remote.call('agent', 'list_agents') or {} "
            f"for _, a in pairs(agents) do if a.interface_name == '{iface}' then "
            "local f = game.forces[a.force]; local n = 0 "
            "for _, t in pairs(f.technologies) do if t.researched then n = n + 1 end end "
            "return n end end return 0"
        )
        return int(n or 0)

    def inventory_counts(self) -> Dict[str, int]:
        inv = getattr(self._tier4, "inventory", None) if self._tier4 else None
        if inv is None:
            inv = getattr(self._tier4, "_inventory", None) if self._tier4 else None
        if inv is None:
            return {}
        try:
            out: Dict[str, int] = {}
            for stack in inv.item_stacks:
                out[stack.name] = out.get(stack.name, 0) + int(stack.count)
            return out
        except Exception as e:
            logger.debug(f"inventory read failed: {e}")
            return {}

    def research_status(self) -> Dict[str, Any]:
        r = getattr(self._tier4, "_research", None) if self._tier4 else None
        if r is None:
            return {}
        try:
            st = r.status()
            return {
                "current_research": st.current_research,
                "progress": st.progress,
                "queue_length": st.queue_length,
                "queue": [q.name for q in st.queue],
            }
        except Exception as e:
            logger.debug(f"research read failed: {e}")
            return {}

    def crafting_queue(self) -> List[Dict[str, Any]]:
        c = getattr(self._tier4, "_crafting", None) if self._tier4 else None
        if c is None:
            return []
        try:
            return list(c.status().get("queue") or [])
        except Exception as e:
            logger.debug(f"crafting read failed: {e}")
            return []

    def take_craft_predictions(self):
        """Predictions the crafting action stored at enqueue (§7.1), taken once."""
        c = getattr(self._tier4, "_crafting", None) if self._tier4 else None
        take = getattr(c, "take_predictions", None)
        return list(take()) if take is not None else []

    def map_rows(self) -> tuple:
        """(entity rows, ghost rows) keyed by name+position, from the map model."""
        rv = self.remote_view
        if rv is None or not getattr(rv, "is_loaded", False):
            return {}, {}
        from FactoryVerse.game.agent.turn_report import index_rows

        try:
            ents = rv.query("SELECT entity_name, position_x, position_y, direction FROM map_entity")
            ghosts = rv.query("SELECT ghost_name, position_x, position_y, direction FROM ghost")
        except Exception as e:
            logger.debug(f"map diff read failed: {e}")
            return {}, {}
        return index_rows(ents, "entity_name"), index_rows(ghosts, "ghost_name")

    @property
    def status_reader(self):
        """The raw status-dump reader (API plan §4.2), or None offline."""
        if self._status_reader is None and self._tier3 is not None:
            try:
                from FactoryVerse.game.agent.status_dump import StatusDumpReader
                from FactoryVerse.environment.config import FactoryVerseConfig

                base = FactoryVerseConfig().get_script_output_dir(self._tier3.instance or "client")
                self._status_reader = StatusDumpReader(base / "factoryverse" / "status")
            except Exception as e:
                logger.debug(f"status reader unavailable: {e}")
        return self._status_reader

    def recipe_energy(self, recipe: str) -> Optional[float]:
        """Recipe energy in seconds from the prototype data (None if unknown)."""
        if recipe in self._energy_cache:
            return self._energy_cache[recipe]
        value: Optional[float] = None
        try:
            from FactoryVerse.game.factory.prototype_data import get_prototype_manager

            raw = get_prototype_manager().get_raw_data()
            proto = (raw.get("recipe") or {}).get(recipe)
            if proto is not None:
                value = float(proto.get("energy_required", 0.5))
        except Exception:
            value = None
        self._energy_cache[recipe] = value
        return value

    def get_game_tick(self) -> Optional[int]:
        """Current game tick, or None when there is no engine to ask.

        Never a fake number (TURN_CONTRACT §4 Clock): a missing tick is an
        honest gap in the record; an invented one blames time on the wrong
        thing.
        """
        if not self._tier3:
            return None
        try:
            return int(self._tier3.get_game_tick())
        except Exception:
            return None

    def _stamp(self, before: Optional[int], text: str) -> str:
        """Append the visible clock trailer and remember the span.

        ``[tick 1200→1260, +60]`` is the HUD plan's rule 1 — a clock the
        model can subtract from — and it costs one RCON call after the call
        (plus one before). With no engine the trailer is omitted.
        """
        after = self.get_game_tick() if before is not None else None
        if before is None or after is None:
            self.last_tick_span = None
            return text
        self.last_tick_span = {"before": before, "after": after}
        return f"{text}\n[tick {before}→{after}, +{after - before}]"

    @property
    def remote_view(self):
        """Expose tier4's RemoteView through the adapter.

        DIGEST-1 (2026-07-12): the orchestrator's power digest reads
        `runtime.remote_view`; this adapter didn't expose it, so the digest
        silently omitted itself on every eval turn (same adapter-missing-
        attribute class as the PROMPT-3 `scenario` skip). Any orchestrator
        surface that reads runtime state must be reachable THROUGH this
        adapter, not only on tier4 directly.
        """
        return self._tier4.remote_view if self._tier4 else None

    @property
    def events(self):
        """Get EventStream for temporal perception of game events.

        The EventStream provides a clean, typed API for consuming
        asynchronous game events (research completions, crafting, etc.).

        This is the preferred way to access game notifications:
            events = await runtime.events.drain()
            for event in events:
                print(f"Event: {event}")

        Returns:
            EventStream instance or None if not available
        """
        if self._tier4:
            return self._tier4.events
        return None

    @property
    def _listener(self):
        """Expose the AsyncActionListener for notification access.

        DEPRECATED: Use runtime.events instead for cleaner API.

        The orchestrator uses this to check for async notifications:
            await runtime._listener.get_notifications(timeout=0.05)
        """
        if self._tier3:
            return self._tier3._action_listener
        return None

    async def execute_dsl(self, code: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Execute DSL code (Python, not Lua).

        The FactoryVerse DSL is Python code using the agent API
        (walking, crafting, reachable_view, etc.), not Lua.
        """
        before = self.get_game_tick()
        text = await self.execute_code(code, compress_output=True, mode=self.turn_mode)
        return self._stamp(before, text)

    def execute_duckdb(
        self, query: str, metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Execute a read-only DuckDB query and return a legible table.

        ONE DB (CELL-1 item 6): when RemoteView is loaded, route through its
        connection (same flush-before-read + lock as remote_view.query) so
        the two agent query paths can never serve different truths. Tier4's
        own database is only the fallback for MINIMAL/partial runtimes.

        Read-only is enforced here rather than left to RemoteView.execute_raw,
        which deliberately drops the SELECT restriction: the agent's query tool
        must not be a write channel into its own map model. A rejected
        statement is returned as data, never raised.

        The result carries column headers, a row count, and an explicit notice
        when it was capped — a bare list of tuples tells the model neither what
        it is looking at nor whether it is looking at all of it.
        """
        refusal = check_read_only(query)
        if refusal is not None:
            self.last_tick_span = None
            return refusal

        before = self.get_game_tick()
        try:
            columns, rows, total = self._fetch_duckdb_rows(query)
        except _NoDatabase:
            return self._stamp(before, "Database not available")
        except Exception as exc:  # surfaced as data: the model cannot catch it
            detail = str(exc)
            if len(detail) > 1000:
                detail = detail[:1000] + "…"
            return self._stamp(before, f"Query error: {type(exc).__name__}: {detail}")

        rendered = _render_query_result(columns, rows, total)

        from FactoryVerse.infra.llm.context.compressor import OutputCompressor

        # Rows are already capped above; the +4 keeps the compressor's row
        # logic from mistaking this table's trailing cap notice for data rows.
        compressed = OutputCompressor().compress_query_result(
            rendered,
            max_rows=self._DUCKDB_MAX_ROWS + 4,
            max_chars=self._DUCKDB_MAX_CHARS,
        )
        return self._stamp(before, compressed.text)

    def _fetch_duckdb_rows(self, query: str):
        """Return (column_names_or_None, rows, total_row_count).

        Rows are capped at ``_DUCKDB_MAX_ROWS`` for rendering, but ``total``
        is the real count so the caller can say how much it is hiding.
        """
        max_rows = self._DUCKDB_MAX_ROWS
        remote_view = self._tier4.remote_view if self._tier4 else None
        if remote_view is not None:
            try:
                if remote_view.is_loaded:
                    # query() returns dicts, so column names survive. It takes
                    # only SELECT/WITH; DESCRIBE/SHOW/PRAGMA and anything its
                    # own prefix check rejects fall back to the raw path
                    # (already proven read-only above) and lose their headers.
                    if leading_keyword(query) in ("SELECT", "WITH"):
                        try:
                            dict_rows = remote_view.query(query)
                        except ValueError:
                            dict_rows = None
                        if dict_rows is not None:
                            columns = (
                                list(dict_rows[0].keys()) if dict_rows else None
                            )
                            rows = [
                                [row.get(col) for col in (columns or [])]
                                for row in dict_rows[:max_rows]
                            ]
                            return columns, rows, len(dict_rows)
                    tuples = remote_view.execute_raw(query)
                    return None, [list(r) for r in tuples[:max_rows]], len(tuples)
            except RuntimeError:
                pass  # not loaded yet — fall through to tier4 database

        if self._tier4 and self._tier4.database:
            cursor = self._tier4.database.execute(query)
            columns = (
                [desc[0] for desc in cursor.description] if cursor.description else None
            )
            tuples = cursor.fetchall()
            return columns, [list(r) for r in tuples[:max_rows]], len(tuples)

        raise _NoDatabase()

    def respond(self, message: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Return chat response."""
        return message

    def get_tool_definitions(
        self,
        mode: str = "autonomous",
        *,
        horizon_ticks: Optional[int] = None,
        turn_mode: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get tool definitions for the LLM.

        Defined once in ``environment.tool_definitions`` — this is the live
        path, and it used to carry the thinnest of three divergent copies.
        """
        return _shared_tool_definitions(
            mode=mode, horizon_ticks=horizon_ticks, turn_mode=turn_mode or self.turn_mode
        )

    async def execute_code(
        self, code: str, compress_output: bool = False, mode: str = "gameplay"
    ) -> str:
        """Execute Python code and return output.

        Uses Tier 4's execute_code method which provides:
        - In-process execution with access to all Tier 4 modules
        - Notebook logging if JUPYTER mode is configured
        - Native async code support (await statements work directly)

        Note: For async code (with 'await'), Tier 4 wraps and awaits directly.
        """
        if self._tier4:
            try:
                return await self._tier4.execute_code(
                    code, compress_output=compress_output, mode=mode
                )
            except TypeError:
                # Older tier4 signature (tests' fakes): no mode parameter.
                return await self._tier4.execute_code(code, compress_output=compress_output)

        # Fallback if Tier 4 not available (shouldn't happen in normal use)
        return "Error: Tier 4 (Runtime) not initialized"
