"""Agent orchestrator for LLM-powered Factorio gameplay.

This module provides the main orchestration loop for LLM agents,
using the LLMClient abstraction for provider-agnostic operation.
"""

import json
import logging
import datetime
from typing import Optional, Dict, Any, Protocol, TYPE_CHECKING, Callable, Awaitable
import tiktoken

from FactoryVerse.infra.llm.client.base import LLMClient, ChatMessage
from FactoryVerse.infra.llm.trajectory import TrajectoryManager, ActionStatus
from FactoryVerse.infra.llm.context.validator import ToolValidator
from FactoryVerse.infra.llm.context.progress_dedupe import ProgressDeduper
from FactoryVerse.infra.output.console import ConsoleOutput
from FactoryVerse.infra.session.trajectory import TrajectoryWriter
from FactoryVerse.game.agent import turn_report as _tr

if TYPE_CHECKING:
    from FactoryVerse.game.tasks.base import TaskConfig, VerificationResult
    from FactoryVerse.game.tasks.sources import VerificationSource

logger = logging.getLogger(__name__)


# Type alias for verification callback
VerificationCallback = Callable[[], Awaitable[Optional["VerificationResult"]]]


class RuntimeProtocol(Protocol):
    """Protocol for runtime objects that can execute code and provide tool definitions."""

    def execute_dsl(self, code: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Execute DSL code."""
        ...

    def execute_duckdb(
        self, query: str, metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Execute DuckDB query."""
        ...

    def respond(self, message: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Return message as response."""
        ...

    def get_tool_definitions(self, mode: str = "autonomous", **kwargs: Any) -> list:
        """Get tool definitions for LLM (kwargs: horizon_ticks, turn_mode)."""
        ...

    def execute_code(self, code: str, compress_output: bool = False) -> str:
        """Execute arbitrary code."""
        ...


class AgentOrchestrator:
    """Orchestrator for LLM agent gameplay.

    This is the main orchestration class that manages the conversation loop
    between an LLM and the FactoryVerse runtime. It:
    - Manages message history
    - Calls the LLM with tool definitions
    - Executes tool calls
    - Handles context compression
    - Tracks action trajectory
    """

    def __init__(
        self,
        llm_client: LLMClient,
        runtime: RuntimeProtocol,
        system_prompt_path: str = "factoryverse-system-prompt.md",
        chat_log_path: Optional[str] = None,
        console_output: Optional[ConsoleOutput] = None,
        trajectory_writer: Optional[TrajectoryWriter] = None,
        initial_state_path: Optional[str] = None,
        max_context_tokens: int = 100000,
        keep_recent_turns: int = 10,
        mode: str = "autonomous",
        task_config: Optional["TaskConfig"] = None,
        verification_callback: Optional[VerificationCallback] = None,
        turn_config: Optional[Any] = None,
    ):
        """
        Initialize orchestrator.

        Args:
            llm_client: LLM client (any provider implementing LLMClient)
            runtime: Runtime object with execute_dsl, execute_duckdb, etc.
            system_prompt_path: Path to system prompt
            chat_log_path: Optional path to save chat log in markdown
            console_output: Optional console output handler for clean display
            trajectory_writer: Optional TrajectoryWriter for trajectory.jsonl persistence
            initial_state_path: Optional path to initial state markdown to inject as first message
            max_context_tokens: Maximum context window size before compression (default: 100k)
            keep_recent_turns: Number of recent turns to preserve during compression (default: 10)
            mode: 'assisted' or 'autonomous' - determines available tools and behavior
            task_config: Optional task configuration for verification
            verification_callback: Optional async callback to run verification
        """
        self.llm_client = llm_client
        self.runtime = runtime
        self.trajectory_manager = TrajectoryManager()
        self.tool_validator = ToolValidator()
        self.turn_number = 0
        self.chat_log_path = chat_log_path
        self.console = console_output or ConsoleOutput(enabled=False)
        self.trajectory = trajectory_writer  # Optional: writes to trajectory.jsonl
        self.max_context_tokens = max_context_tokens
        self.keep_recent_turns = keep_recent_turns
        self.mode = mode
        self.max_turns: Optional[int] = None  # None = unlimited
        self._task_completed: bool = False  # Set by verification or done() tool
        self._task_config: Optional["TaskConfig"] = task_config
        self._verification_callback: Optional[VerificationCallback] = verification_callback
        self._last_verification_result: Optional["VerificationResult"] = None
        # OBS-2: collapse verbatim-repeated Task Progress blocks before they
        # enter (and compound in) the LLM message history. Full block is emitted
        # on every content change and refreshed periodically; only byte-identical
        # repeats become one-line pointers.
        self._progress_deduper = ProgressDeduper(refresh_every=10)

        # --- The turn contract (TURN_CONTRACT §3–§6) -----------------------
        if turn_config is None:
            from FactoryVerse.environment.config import TurnConfig

            turn_config = TurnConfig()
        self.turn_config = turn_config
        # The first turn is a planning turn (§6): report as input, map-scale
        # reads and research as namespace, end_turn advancing nothing.
        self.turn_mode: str = "planning"
        self._next_horizon: int = turn_config.t_min
        self._pending_report_text: Optional[str] = None
        self._last_report: Optional[_tr.TurnReport] = None
        self._last_events: list = []

        # Load system prompt
        try:
            with open(system_prompt_path, "r") as f:
                system_prompt = f.read()
        except FileNotFoundError:
            logger.warning(f"System prompt not found: {system_prompt_path}")
            system_prompt = "You are a Factorio automation agent."

        self.messages: list[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt}
        ]
        # The record stores the prompt once; every inference_input references it.
        self._system_prompt_sha256: Optional[str] = None
        if self.trajectory:
            self._system_prompt_sha256 = self.trajectory.system_prompt(system_prompt)

        # Initialize chat log
        if self.chat_log_path:
            with open(self.chat_log_path, "w") as f:
                f.write("# Factorio Agent Chat Log\n\n")
                f.write(f"Session started at {datetime.datetime.now().isoformat()}\n\n")
                f.write("---\n\n")

        # Inject initial state as first user message if provided
        if initial_state_path:
            try:
                with open(initial_state_path, "r") as f:
                    initial_state = f.read()

                # Add as first user message
                self.messages.append(
                    {
                        "role": "user",
                        "content": f"Here is your initial game state:\n\n{initial_state}",
                    }
                )

                # Log to chat
                if self.chat_log_path:
                    with open(self.chat_log_path, "a") as f:
                        f.write("**System:** Initial game state loaded\n\n")
                        f.write(
                            f"<details>\n<summary>Initial State</summary>\n\n{initial_state}\n\n</details>\n\n"
                        )
                        f.write("---\n\n")

                logger.info(f"Injected initial state from {initial_state_path}")
            except FileNotFoundError:
                logger.warning(f"Initial state file not found: {initial_state_path}")
            except Exception as e:
                logger.error(f"Error loading initial state: {e}")

    def load_from_trajectory(
        self,
        trajectory_reader: "TrajectoryReader",
        system_prompt: Optional[str] = None,
        initial_state: Optional[str] = None,
    ) -> None:
        """Load orchestrator state from trajectory.
        
        Reconstructs message history and trajectory manager state from
        trajectory.jsonl events. This allows continuing a trajectory.
        
        Args:
            trajectory_reader: TrajectoryReader instance with loaded events
            system_prompt: Optional system prompt to use (default: from file)
            initial_state: Optional initial state content (default: from file)
        """
        from FactoryVerse.infra.session.trajectory import TrajectoryReader
        
        # Get session info
        session_info = trajectory_reader.get_session_info()
        if session_info:
            logger.info(
                f"Loading trajectory: model={session_info.get('model')}, "
                f"mode={session_info.get('mode')}"
            )
        
        # Reconstruct message history
        trajectory_messages = trajectory_reader.build_message_history()
        
        # Start with system prompt
        if system_prompt:
            self.messages = [{"role": "system", "content": system_prompt}]
        else:
            # Try to load from file
            try:
                with open(self.system_prompt_path, "r") as f:
                    system_prompt = f.read()
                self.messages = [{"role": "system", "content": system_prompt}]
            except FileNotFoundError:
                logger.warning("System prompt not found, using default")
                self.messages = [{"role": "system", "content": "You are a Factorio automation agent."}]
        
        # Add initial state if provided
        if initial_state:
            self.messages.append({
                "role": "user",
                "content": f"Here is your initial game state:\n\n{initial_state}",
            })
        
        # Add trajectory messages (skip initial state if already added)
        # Find where to start adding (after system + initial state)
        start_idx = 0
        if initial_state and trajectory_messages:
            # Check if first message is initial state
            first_msg = trajectory_messages[0]
            if first_msg.get("role") == "user" and "initial game state" in first_msg.get("content", "").lower():
                start_idx = 1
        
        self.messages.extend(trajectory_messages[start_idx:])
        
        # Load trajectory manager state
        events = trajectory_reader.read_all()
        self.trajectory_manager.load_from_trajectory_events(events)
        
        # Determine current turn number
        turns = trajectory_reader.build_turns()
        if turns:
            # Get the highest turn number
            max_turn = max(turns.keys())
            # If last turn is complete, next turn is max_turn + 1
            # Otherwise, continue with max_turn
            last_turn = turns[max_turn]
            if last_turn.is_complete:
                self.turn_number = max_turn + 1
            else:
                self.turn_number = max_turn
        else:
            self.turn_number = 0
        
        logger.info(f"Loaded trajectory: {len(self.messages)} messages, turn_number={self.turn_number}")

    async def run_turn(self, user_message: str) -> str:
        """
        Run one turn under the turn contract (TURN_CONTRACT §3):

        - the pending turn report (the observation) is the first thing in the
          model's input; ``user_message`` follows it if non-empty;
        - N tool calls of attention (``turn_config.attention_calls``); the
          turn ends on ``end_turn``, a text reply, ``respond``, verification,
          or the attention cap — every exit is named on the record;
        - nothing is injected inside the turn: events are drained once at the
          boundary, into the next report;
        - ``end_turn`` fast-forwards ``max(0, T − ticks used)`` (zero in a
          planning turn), then the report is assembled.

        Returns:
            Agent's text response (or the turn's closing line)
        """
        if not self.has_turns_remaining():
            error_msg = f"Max turns limit reached ({self.max_turns} turns). Cannot execute more turns."
            logger.warning(error_msg)
            return error_msg

        mode = self.turn_mode
        if hasattr(self.runtime, "turn_mode"):
            self.runtime.turn_mode = mode
        plan_store = getattr(self.runtime, "plan_store", None)
        if plan_store is not None and hasattr(plan_store, "bind_turn"):
            plan_store.bind_turn(self.turn_number)

        # The report is the observation (§21): delivered as input, never fetched.
        parts = []
        if self._pending_report_text:
            parts.append(self._pending_report_text)
        elif self.turn_number == 0:
            parts.append(self._opening_line())
        if user_message:
            parts.append(user_message)
        message = "\n\n".join(parts)
        self._pending_report_text = None

        self._log_to_chat(f"**User:** {message}\n\n")
        self.console.user_message(message)
        if self.trajectory:
            self.trajectory.user_message(message, turn=self.turn_number)
        self.messages.append({"role": "user", "content": message})

        horizon = 0 if mode == "planning" else self._next_horizon
        # The turn starts at the previous turn's boundary tick (read while the
        # engine was paused), so the ticks that ran between the unpause and
        # this inference are this turn's thinking, not nobody's (§17).
        turn_start_tick = getattr(self, "_next_turn_start_tick", None)
        if turn_start_tick is None:
            turn_start_tick = self._game_tick()
        self._next_turn_start_tick = None
        before = self._snapshot(turn_start_tick)

        tool_calls_executed = 0
        execution_ticks = 0
        tool_results = []
        ended_by: Optional[str] = None
        response_text = ""

        for iteration in range(1, self.turn_config.inference_sanity_cap + 1):
            logger.info(f"Turn {self.turn_number}: Calling LLM (iteration {iteration})...")
            self.console.llm_thinking(iteration)
            self._check_and_compress_context()

            tools = self._tools_for(horizon if mode != "planning" else None, mode)

            if self.trajectory:
                self.trajectory.inference_input(
                    turn=self.turn_number,
                    iteration=iteration,
                    messages=self.messages,
                    tools=tools,
                    game_tick=self._game_tick(),
                    system_prompt_sha256=self._system_prompt_sha256,
                )

            result = self.llm_client.chat_completion(messages=self.messages, tools=tools)
            response: ChatMessage = result.message
            response_dict = response.to_dict()
            self.messages.append(response_dict)
            if self.trajectory:
                self.trajectory.inference_output(
                    turn=self.turn_number,
                    iteration=iteration,
                    message=response_dict,
                    finish_reason=getattr(result, "finish_reason", None),
                    model=getattr(result, "model", None),
                )
            self._record_usage(result, response)

            if not response.has_tool_calls:
                logger.info(f"Turn {self.turn_number}: Agent responded with text")
                if not response.content or response.content.strip() == "":
                    logger.warning(f"Turn {self.turn_number}: LLM returned empty content!")
                    response_text = "I apologize, I don't have a response. Could you rephrase your request?"
                else:
                    response_text = response.content
                self._log_to_chat(f"**Agent:** {response_text}\n\n")
                self._log_to_chat("---\n\n")
                self.console.assistant_response(response_text, self.turn_number)
                if self.trajectory:
                    self.trajectory.assistant_response(response_text, turn=self.turn_number)
                ended_by = "text_response"
                break

            tool_calls = response.tool_calls or []
            logger.info(f"Turn {self.turn_number}: Executing {len(tool_calls)} tool calls...")
            self._log_to_chat("<details>\n<summary>Tool calls</summary>\n\n")

            for tool_call in tool_calls:
                tool_name = tool_call.name
                call_id = tool_call.id
                logger.info(f"  Tool: {tool_name}")
                self.console.tool_call_start(tool_name, iteration)
                if self.trajectory:
                    self.trajectory.tool_start(tool_name, turn=self.turn_number, iteration=iteration)

                arguments: Dict[str, Any] = {}
                try:
                    arguments = tool_call.parse_arguments() or {}
                    self._log_tool_call(tool_name, arguments)

                    if ended_by is not None:
                        # A call after end_turn in the same batch: the turn is
                        # over; say so rather than silently running it.
                        exec_result = "❌ The turn already ended (end_turn was called earlier in this batch)."
                        status = ActionStatus.FAILURE
                    elif tool_name == "end_turn":
                        exec_result = self._end_turn_result(mode, horizon, turn_start_tick)
                        status = ActionStatus.SUCCESS
                        ended_by = "end_turn"
                    else:
                        validation = self.tool_validator.validate_tool_call(tool_name, arguments)
                        if not validation.valid:
                            exec_result = f"❌ Validation error: {validation.error}"
                            status = ActionStatus.FAILURE
                        else:
                            parsed_args = validation.parsed_arguments or {}
                            exec_result, status = await self._execute_tool(tool_name, parsed_args)
                            tool_calls_executed += 1
                            span = getattr(self.runtime, "last_tick_span", None) or {}
                            if span.get("before") is not None and span.get("after") is not None:
                                execution_ticks += int(span["after"]) - int(span["before"])

                    self._log_to_chat(f"**Result:**\n```\n{exec_result}\n```\n\n")
                    is_error = (
                        exec_result.startswith("❌")
                        or exec_result.startswith("Error:")
                        or status == ActionStatus.FAILURE
                    )
                    self.console.tool_result(exec_result, is_error=is_error)
                    if self.trajectory:
                        span = getattr(self.runtime, "last_tick_span", None) or {}
                        self.trajectory.tool_result(
                            exec_result,
                            turn=self.turn_number,
                            success=not is_error,
                            game_tick_before=span.get("before") if tool_name != "end_turn" else None,
                            game_tick_after=span.get("after") if tool_name != "end_turn" else None,
                        )
                    tool_results.append({"tool": tool_name, "result": exec_result})
                except json.JSONDecodeError as e:
                    exec_result = f"❌ Invalid JSON arguments: {str(e)}"
                    status = ActionStatus.FAILURE
                    self._log_to_chat(f"**Error:** {exec_result}\n\n")
                    self.console.tool_result(exec_result, is_error=True)
                except Exception as e:
                    exec_result = f"❌ Execution error: {str(e)}"
                    status = ActionStatus.FAILURE
                    self._log_to_chat(f"**Error:** {exec_result}\n\n")
                    self.console.tool_result(exec_result, is_error=True)

                self.trajectory_manager.add_action(
                    tool_name=tool_name,
                    arguments=arguments,
                    result=exec_result,
                    compressed_result=exec_result,
                    turn_number=self.turn_number,
                    status=status,
                    metadata={"tool_call_id": call_id},
                )
                self.messages.append({"role": "tool", "tool_call_id": call_id, "content": exec_result})
                logger.info(
                    f"  Result: {exec_result[:100]}..." if len(exec_result) > 100 else f"  Result: {exec_result}"
                )

                if ended_by is None and tool_calls_executed >= self.turn_config.attention_calls:
                    ended_by = "attention_cap"

            self._log_to_chat("</details>\n\n")

            # Task verification still runs inside the turn (it is the task's
            # own gate, not a world event) and may end the run.
            verification_msg = await self._check_task_verification()
            if verification_msg:
                rendered_progress = self._progress_deduper.render(verification_msg, turn=self.turn_number)
                self.messages.append({"role": "user", "content": rendered_progress})
                self._log_to_chat(f"**Task Progress:**\n```\n{rendered_progress}\n```\n\n")
                self._log_to_chat("---\n\n")
                self.console.system_notification(verification_msg)
                if self._task_completed:
                    logger.info("AgentOrchestrator: Task completed via verification")
                    ended_by = "verification"
                    response_text = "Task completed successfully!"

            if ended_by is None and any(tc.name == "respond" for tc in tool_calls):
                for tool_result in tool_results:
                    if tool_result["tool"] == "respond":
                        response_text = tool_result["result"]
                        self._log_to_chat(f"**Agent:** {response_text}\n\n")
                        self._log_to_chat("---\n\n")
                        self.console.assistant_response(response_text, self.turn_number)
                        ended_by = "respond"
                        break

            if ended_by is not None:
                break
        else:
            logger.warning(f"Turn {self.turn_number}: inference sanity cap reached")
            self.console.max_iterations_warning(self.turn_number)
            ended_by = "inference_cap"
            response_text = "Inference cap reached without ending the turn."

        if ended_by == "attention_cap":
            self.console.max_iterations_warning(self.turn_number)
            response_text = response_text or "Attention budget spent; the turn ended."

        await self._close_turn(
            mode=mode,
            ended_by=ended_by or "unknown",
            horizon=horizon,
            turn_start_tick=turn_start_tick,
            before=before,
            execution_ticks=execution_ticks,
        )
        return response_text or f"Turn ended ({ended_by})."

    # ------------------------------------------------------------------
    # Turn boundary
    # ------------------------------------------------------------------

    def _opening_line(self) -> str:
        return (
            f"# Turn 1 — {self.turn_mode.upper()} turn\n\n"
            "This is a planning turn: read the map and the research state, set "
            "your plan with plan.set(...) and plan.set_goals([...]), queue "
            "research if you wish, then call end_turn. Gameplay turns follow; "
            "each opens with a report of what changed."
            if self.turn_mode == "planning"
            else f"# Turn 1 — GAMEPLAY turn (horizon {self._next_horizon} ticks)"
        )

    def _tools_for(self, horizon: Optional[int], mode: str) -> list:
        try:
            return self.runtime.get_tool_definitions(mode=self.mode, horizon_ticks=horizon, turn_mode=mode)
        except TypeError:
            # A runtime with the old one-argument signature.
            return self.runtime.get_tool_definitions(mode=self.mode)

    def _end_turn_result(self, mode: str, horizon: int, turn_start_tick: Optional[int]) -> str:
        now = self._game_tick()
        used = (now - turn_start_tick) if (now is not None and turn_start_tick is not None) else None
        if mode == "planning":
            return "Turn ended. Planning turn: no world time advances. Your report follows."
        if used is None:
            return "Turn ended. The world advances to the horizon; your report follows."
        remaining = max(0, horizon - used)
        return (
            f"Turn ended at tick {now}: you used {used} of {horizon} ticks; the world "
            f"now advances the remaining {remaining}. Your report follows."
        )

    async def _close_turn(
        self,
        *,
        mode: str,
        ended_by: str,
        horizon: int,
        turn_start_tick: Optional[int],
        before: Optional[_tr.TurnSnapshot],
        execution_ticks: int,
    ) -> None:
        """Fast-forward, drain once, assemble the report, pick the next mode."""
        end_tick = self._game_tick()
        advanced = 0
        boundary_tick: Optional[int] = None
        if mode != "planning" and end_tick is not None and turn_start_tick is not None:
            target = turn_start_tick + horizon
            # Prefer the frozen form: pause first, then compute the remainder
            # on the paused tick, so no tick runs between "the turn ended" and
            # "the advance began" (§17). Fall back to the pre-computed form
            # for runtimes that only offer advance_world.
            advance_to = getattr(self.runtime, "advance_world_to", None)
            advance = getattr(self.runtime, "advance_world", None)
            try:
                result = None
                if advance_to is not None:
                    result = advance_to(target)
                elif advance is not None:
                    wanted = max(0, horizon - (end_tick - turn_start_tick))
                    result = advance(wanted) if wanted > 0 else None
                if result is not None:
                    advanced = int(getattr(result, "advanced", result))
                    boundary_tick = getattr(result, "end_tick", None)
                    frozen_start = getattr(result, "start_tick", None)
                    if frozen_start is not None:
                        end_tick = frozen_start  # the turn ended when the world froze
            except Exception as e:
                logger.error(f"fast-forward failed: {e}")
                advanced = 0
        # The boundary tick was read while paused; it is the report's tick and
        # the next turn's start. Only when nothing advanced do we read live.
        final_tick = boundary_tick if boundary_tick is not None else self._game_tick()
        self._next_turn_start_tick = final_tick

        # The one drain per turn (§21): everything that fired during the turn
        # and the advance, in order, into the report's Events section.
        events = await self._drain_events()
        self._last_events = events
        seq_gaps = [e.to_dict() for e in events if getattr(e, "notification_type", None) == "sequence_gap" and hasattr(e, "to_dict")]

        after = self._snapshot(final_tick)
        clock = _tr.ClockLedger(
            turn_start_tick=turn_start_tick or 0,
            end_turn_tick=end_tick if end_tick is not None else (turn_start_tick or 0),
            advanced=advanced,
            final_tick=final_tick if final_tick is not None else (end_tick or turn_start_tick or 0),
            execution_ticks=execution_ticks,
            horizon=horizon,
        )

        status_change = None
        reader = getattr(self.runtime, "status_reader", None)
        if reader is not None and turn_start_tick is not None:
            try:
                status_change = reader.changed(turn_start_tick)
            except Exception as e:
                logger.debug(f"status diff skipped: {e}")

        researched = after.researched_count if after else 0
        # Provisional rate; the assembler computes the final one from the diff.
        report = _tr.assemble(
            turn=self.turn_number,
            mode=mode,
            ended_by=ended_by,
            clock=clock,
            before=before or self._empty_snapshot(turn_start_tick or 0),
            after=after or self._empty_snapshot(clock.final_tick),
            events=events,
            status_change=status_change,
            next_horizon=self._next_horizon,
            next_inputs={},
            energy_for=self._energy_for,
            plan=self._plan_snapshot(),
            seq_gaps=seq_gaps,
        )
        rate = report.production["automated_rate_per_min"]
        self._next_horizon = self.turn_config.horizon_ticks(researched, rate)
        report.horizon = {
            "next_ticks": self._next_horizon,
            "inputs": {
                "research_tier": self.turn_config.research_tier(researched),
                "researched_count": researched,
                "automated_rate_per_min": rate,
            },
        }
        # Next mode (§6): planning after a research completion, else gameplay.
        research_done = any(getattr(e, "notification_type", None) == "research_finished" for e in events)
        self.turn_mode = "planning" if research_done else "gameplay"
        report_dict = report.to_dict()
        report_dict["next_mode"] = self.turn_mode
        rendered = _tr.render(report).replace(
            f"# Turn {self.turn_number + 1} — {mode.upper()} turn",
            f"# Turn {self.turn_number + 2} — {self.turn_mode.upper()} turn",
            1,
        )
        self._last_report = report
        self._pending_report_text = rendered

        if self.trajectory:
            self.trajectory.turn_report(turn=self.turn_number, report=report_dict, rendered=rendered)
            if events:
                self.trajectory.notification(
                    rendered,
                    turn=self.turn_number,
                    index=None,
                    events=[_event_payload(e) for e in events],
                )
            self.trajectory.turn_complete(turn=self.turn_number, ended_by=ended_by)
        self._log_to_chat(f"**Turn report (next turn's input):**\n```\n{rendered}\n```\n\n---\n\n")
        if hasattr(self.console, "system_notification"):
            self.console.system_notification(
                f"turn {self.turn_number} ended by {ended_by}: used {clock.used}, advanced {advanced}, "
                f"next horizon {self._next_horizon} ({self.turn_mode})"
            )
        self.console.turn_complete(self.turn_number)
        self.turn_number += 1

    def _snapshot(self, tick: Optional[int]) -> Optional[_tr.TurnSnapshot]:
        """Capture the report's inputs; None when the runtime has no reads."""
        rt = self.runtime
        if not hasattr(rt, "production_statistics"):
            return None
        try:
            ents, ghosts = rt.map_rows() if hasattr(rt, "map_rows") else ({}, {})
            return _tr.TurnSnapshot(
                tick=tick or 0,
                production=rt.production_statistics(),
                inventory=rt.inventory_counts() if hasattr(rt, "inventory_counts") else {},
                map_rows=ents,
                ghost_rows=ghosts,
                research=rt.research_status() if hasattr(rt, "research_status") else {},
                crafting_queue=rt.crafting_queue() if hasattr(rt, "crafting_queue") else [],
                researched_count=rt.researched_count() if hasattr(rt, "researched_count") else 0,
            )
        except Exception as e:
            logger.warning(f"turn snapshot failed: {e}")
            return None

    @staticmethod
    def _empty_snapshot(tick: int) -> _tr.TurnSnapshot:
        return _tr.TurnSnapshot(tick=tick, production={"input": {}, "output": {}}, inventory={},
                                map_rows={}, ghost_rows={}, research={}, crafting_queue=[], researched_count=0)

    def _energy_for(self, recipe: str) -> Optional[float]:
        fn = getattr(self.runtime, "recipe_energy", None)
        if fn is None:
            return None
        try:
            return fn(recipe)
        except Exception:
            return None

    def _plan_snapshot(self) -> Optional[Dict[str, Any]]:
        store = getattr(self.runtime, "plan_store", None)
        if store is None or not hasattr(store, "read"):
            return None
        try:
            return store.read()
        except Exception:
            return None

    @property
    def last_report(self) -> Optional[_tr.TurnReport]:
        return self._last_report

    def _record_usage(self, result: Any, response: ChatMessage) -> None:
        usage_data = None
        if result.usage:
            usage_data = {
                "prompt_tokens": result.usage.prompt_tokens,
                "completion_tokens": result.usage.completion_tokens,
                "total_tokens": result.usage.total_tokens,
            }
            if result.usage.cached_prompt_tokens is not None:
                usage_data["cached_prompt_tokens"] = result.usage.cached_prompt_tokens
        else:
            try:
                usage_data = self._calculate_fallback_usage(self.messages[:-1], response.content or "")
            except Exception as e:
                logger.warning(f"Failed to calculate fallback token usage: {e}")
        if usage_data:
            if self.trajectory:
                self.trajectory.completion_stats(turn=self.turn_number, usage=usage_data)
            self.trajectory_manager.add_completion_stats(usage_data)

    def _log_tool_call(self, tool_name: str, arguments: Dict[str, Any]) -> None:
        if tool_name == "execute_dsl":
            self._log_to_chat(f"**{tool_name}:**\n```python\n{arguments.get('code', '')}\n```\n\n")
            self.console.tool_call_code(arguments.get("code", ""), language="python")
            if self.trajectory:
                self.trajectory.tool_code(arguments.get("code", ""), turn=self.turn_number, lang="python")
        elif tool_name == "execute_duckdb":
            self._log_to_chat(f"**{tool_name}:**\n```sql\n{arguments.get('query', '')}\n```\n\n")
            self.console.tool_call_code(arguments.get("query", ""), language="sql")
            if self.trajectory:
                self.trajectory.tool_code(arguments.get("query", ""), turn=self.turn_number, lang="sql")
        else:
            self._log_to_chat(f"**{tool_name}:** {json.dumps(arguments, indent=2)}\n\n")

    def _game_tick(self) -> Optional[int]:
        """Current game tick via the runtime, or None when there is no engine.

        Never a fake number: a record with no tick is honest; a record with
        a made-up tick is a lie about time.
        """
        getter = getattr(self.runtime, "get_game_tick", None)
        if getter is None:
            return None
        try:
            return getter()
        except Exception as e:  # engine unreachable — say nothing
            logger.debug(f"game tick unavailable: {e}")
            return None

    def _log_to_chat(self, message: str):
        """Append message to chat log file."""
        if self.chat_log_path:
            with open(self.chat_log_path, "a") as f:
                f.write(message)

    async def _execute_tool(
        self, tool_name: str, arguments: Dict[str, Any]
    ) -> tuple[str, ActionStatus]:
        """
        Execute a tool.

        Args:
            tool_name: Tool name
            arguments: Tool arguments

        Returns:
            Tuple of (result, status)
        """
        try:
            metadata = {"tool_name": tool_name, "turn_number": self.turn_number}

            if tool_name == "execute_dsl":
                # execute_dsl may be async (when using Environment tiers)
                coro_or_result = self.runtime.execute_dsl(arguments["code"], metadata=metadata)
                if hasattr(coro_or_result, "__await__"):
                    result = await coro_or_result
                else:
                    result = coro_or_result
                return result, ActionStatus.SUCCESS

            elif tool_name == "execute_duckdb":
                result = self.runtime.execute_duckdb(
                    arguments["query"], metadata=metadata
                )
                return result, ActionStatus.SUCCESS

            elif tool_name == "respond":
                result = self.runtime.respond(arguments["message"], metadata=metadata)
                return result, ActionStatus.SUCCESS

            else:
                return f"❌ Unknown tool: {tool_name}", ActionStatus.FAILURE

        except Exception as e:
            logger.error(f"Error executing {tool_name}: {e}", exc_info=True)
            return f"❌ Execution error: {str(e)}", ActionStatus.FAILURE

    def get_statistics(self) -> Dict[str, Any]:
        """Get trajectory statistics."""
        return self.trajectory_manager.get_statistics()

    def set_max_turns(self, max_turns: Optional[int]) -> None:
        """Set maximum number of turns (None for unlimited).

        Args:
            max_turns: Maximum number of turns, or None for unlimited
        """
        if max_turns is not None and max_turns < 0:
            raise ValueError("max_turns must be None or a non-negative integer")
        self.max_turns = max_turns
        logger.info(f"Max turns set to: {max_turns if max_turns else 'unlimited'}")

    def has_turns_remaining(self) -> bool:
        """Check if agent has turns remaining.

        Returns:
            True if max_turns is None or turn_number < max_turns, False otherwise
        """
        if self._task_completed:
            return False
        if self.max_turns is None:
            return True
        return self.turn_number < self.max_turns

    def mark_task_completed(self) -> None:
        """Mark the task as completed, causing the loop to exit."""
        self._task_completed = True
        logger.info("AgentOrchestrator: Task marked as completed")

    def set_task_config(self, task_config: "TaskConfig") -> None:
        """Set task configuration for verification.

        Args:
            task_config: Task configuration with verification criteria
        """
        self._task_config = task_config

    def set_verification_callback(
        self, callback: VerificationCallback
    ) -> None:
        """Set verification callback for automatic task verification.

        Args:
            callback: Async callback that returns VerificationResult
        """
        self._verification_callback = callback

    async def _check_task_verification(self) -> Optional[str]:
        """Check task verification and return progress message.

        Returns:
            Progress message to inject into conversation, or None if no task/verification
        """
        if self._task_config is None or self._verification_callback is None:
            return None

        try:
            result = await self._verification_callback()
            if result is None:
                return None

            self._last_verification_result = result

            # Log verification check to trajectory
            if self.trajectory:
                self.trajectory.verification_check(
                    turn=self.turn_number,
                    game_tick=result.measured_at_tick or 0,
                    current_rate=result.current_rate or 0.0,
                    target_rate=self._task_config.verification.quota if self._task_config.verification else 0,
                    passed=result.current_rate is not None and self._task_config.verification is not None and result.current_rate >= self._task_config.verification.quota,
                    consecutive_passes=result.consecutive_passes or 0,
                    checks_required=self._task_config.verification.checks_required if self._task_config.verification else 6,
                    automation_produced=result.automation_produced or 0,
                    feed_stale=getattr(result, "feed_stale", False),
                )

            # Format progress message
            progress_msg = self._format_verification_progress(result)

            # Check if task is complete
            if result.success:
                self._task_completed = True
                logger.info(
                    f"AgentOrchestrator: Task verification PASSED! "
                    f"Automation: {result.automation_produced}"
                )

            return progress_msg

        except Exception as e:
            logger.warning(f"AgentOrchestrator: Verification error: {e}")
            return None

    def _format_verification_progress(
        self, result: "VerificationResult"
    ) -> str:
        """Format verification result as progress message.

        For rate-based throughput tasks, shows:
        - Current rate vs target rate
        - Sustained check progress (consecutive passes / required)
        - Recent check history
        - Tick information for staleness awareness

        Args:
            result: VerificationResult with production stats and rate info

        Returns:
            Formatted message showing progress toward task goal
        """
        if self._task_config is None or self._task_config.verification is None:
            return ""

        criteria = self._task_config.verification
        target = criteria.target_item
        quota = criteria.quota
        rate = result.current_rate
        consecutive = result.consecutive_passes
        required = result.checks_required

        # Build progress message
        lines = []

        if result.success:
            lines.append("=" * 50)
            lines.append("✅ TASK COMPLETE!")
            lines.append("=" * 50)
            lines.append(f"Target: {target}")
            lines.append(f"Required rate: {quota}/60s")
            lines.append(f"Sustained rate: {rate:.1f}/60s")
            lines.append(f"Sustained for: {consecutive} consecutive checks")
            lines.append("")
            lines.append("Your factory has sustained the required throughput.")
            lines.append("The task is complete - you may stop.")
            lines.append("=" * 50)
        elif result.feed_stale:
            # VERIF-1: a frozen feed must never render as a normal 0-rate reading
            lines.append("!" * 45)
            lines.append(f"⚠️  VERIFICATION FEED PROBLEM: {target}")
            lines.append("!" * 45)
            if result.failure_reason:
                lines.append(f"  {result.failure_reason}")
            lines.append(f"  Last data at tick: {result.measured_at_tick}")
            lines.append(f"  Last known total: {result.automation_produced} (automation)")
            lines.append(f"  Sustained progress held at: {result.consecutive_passes}/{result.checks_required}")
            lines.append("!" * 45)
        else:
            lines.append("-" * 45)
            lines.append(f"📊 Throughput: {target}")
            lines.append("-" * 45)
            lines.append(f"  Target rate: {quota}/60s")

            # Current rate with pass/fail indicator
            rate_status = "✓" if rate >= quota else "✗"
            lines.append(f"  Current rate: {rate:.1f}/60s {rate_status}")

            # Sustained progress
            sustained_seconds = consecutive * criteria.check_interval_seconds
            required_seconds = criteria.sustained_seconds
            lines.append(
                f"  Sustained: {consecutive}/{required} checks "
                f"({sustained_seconds:.0f}s/{required_seconds:.0f}s)"
            )

            # Visual progress bar for sustained checks
            bar_len = required
            filled = min(consecutive, required)
            bar = "●" * filled + "○" * (bar_len - filled)
            lines.append(f"  Progress: [{bar}]")

            # Recent check history (last 5)
            if result.check_history:
                history = result.check_history[-5:]
                history_str = " ".join("✓" if c.passed else "✗" for c in history)
                lines.append(f"  Last {len(history)}: {history_str}")

                # Show if there was a recent dip (reset)
                for i, check in enumerate(history):
                    if not check.passed and i < len(history) - 1:
                        lines.append(f"           {'  ' * i}↑ dip (reset)")
                        break

            # Cumulative stats
            lines.append(f"  Total produced: {result.automation_produced} (automation)")

            # Tick information for staleness awareness
            # Stats are polled every 60 ticks (1 second), so data may be up to 1s old
            snapshot_tick = result.measured_at_tick
            snapshot_seconds = snapshot_tick / 60.0
            lines.append(f"  Snapshot tick: {snapshot_tick} ({snapshot_seconds:.1f}s game time)")

            if result.failure_reason:
                lines.append(f"  Note: {result.failure_reason}")

            lines.append("-" * 45)

        # ISLAND-1: Task Progress showed throughput only. Add ONE compact power
        # line so the agent sees its networks' gen/load and unpowered members.
        # NEVER throws — a crashing digest kills the run, so any error omits the
        # line (a lying digest is worse than none).
        power_line = self._render_power_digest_line()
        if power_line:
            lines.append(power_line)

        return "\n".join(lines)

    def _render_power_digest_line(self) -> Optional[str]:
        """One compact power line for Task Progress, or None to omit it.

        Format (ISLAND-1):
            power: 2 nets | net@(971.5,971.5) 77.5kW/77.5kW gen/load | net@(1051.5,971.5) 30.0kW/30.0kW 2 low_power

        Never raises: any error (no remote_view, query failure, malformed
        report) returns None and the line is simply omitted.
        """
        try:
            rv = getattr(self.runtime, "remote_view", None)
            if rv is None or not getattr(rv, "is_loaded", False):
                # DIGEST-1: this exact branch silently ate the digest for a full
                # eval run (the runtime adapter didn't expose remote_view).
                # Never-throw stays, but the omission must be observable.
                if not getattr(self, "_power_digest_warned", False):
                    self._power_digest_warned = True
                    logger.warning(
                        "power digest disabled: runtime has no loaded remote_view "
                        f"(runtime={type(self.runtime).__name__}) — "
                        "Task Progress will carry NO power line this session"
                    )
                return None
            report = rv.get_power_networks()
            if report is None or report.sample_tick is None:
                return None  # sampler never ran — omit rather than lie
            # DIGEST-2: no_power machines attached to NO network (not covered
            # by any pole) have no per-net bucket — surface them independently
            # or the digest under-reports exactly the sickest machines.
            orphans = getattr(report, "unattributed_no_power", 0) or 0
            orphan_seg = f" | {orphans} unpowered (no net)" if orphans else ""

            nets = report.networks
            if not nets:
                return "power: no networks" + orphan_seg

            segs = []
            for i, net in enumerate(nets[:3]):
                pos = net.anchor_pole_position or {}
                ax, ay = pos.get("x"), pos.get("y")
                loc = f"({ax:.1f},{ay:.1f})" if ax is not None else "(?)"
                seg = (
                    f"net@{loc} {net.production_w / 1000:.1f}kW/"
                    f"{net.consumption_w / 1000:.1f}kW"
                )
                if i == 0:
                    seg += " gen/load"
                if net.no_power_count:
                    seg += f" {net.no_power_count} no_power"
                if net.low_power_count:
                    seg += f" {net.low_power_count} low_power"
                segs.append(seg)

            line = f"power: {len(nets)} nets | " + " | ".join(segs)
            more = len(nets) - 3
            if more > 0:
                line += f" | +{more} more"
            return line + orphan_seg
        except Exception as e:  # noqa: BLE001 — digest must never kill the run
            logger.debug(f"power digest line skipped: {e}")
            return None

    async def _drain_events(self) -> list:
        """Drain pending game events from the EventStream.

        Uses Tier 4's EventStream for clean access to game notifications.
        Falls back to legacy _listener if EventStream is not available.

        Returns:
            List of GameEvent objects (or raw payloads for legacy path)
        """
        # Preferred path: Use EventStream from runtime.events
        if hasattr(self.runtime, "events") and self.runtime.events is not None:
            try:
                events = await self.runtime.events.drain(timeout=0.05)
                return events
            except Exception as e:
                logger.debug(f"Error draining events: {e}")
                return []

        # Legacy fallback: Use _listener.get_notifications()
        if hasattr(self.runtime, "_listener") and self.runtime._listener is not None:
            try:
                notifications = await self.runtime._listener.get_notifications(timeout=0.05)
                return notifications
            except Exception as e:
                logger.debug(f"Error getting notifications (legacy): {e}")
                return []

        return []

    async def _add_notifications_to_messages(self):
        """Check for events and add them to the message history.

        This is called after tool execution to ensure notifications generated
        during DSL/tool execution are immediately available to the agent.

        Uses EventStream when available for typed events, falls back to
        legacy raw payload handling.
        """
        events = await self._drain_events()

        if not events:
            return

        logger.info(
            f"Found {len(events)} pending event(s) after tool execution"
        )

        # Format events - check if we have EventStream or raw payloads
        event_stream = getattr(self.runtime, "events", None)

        if event_stream is not None:
            # Use EventStream's formatting (typed events)
            combined_notif = event_stream.format_events(events)
        else:
            # Legacy path: format raw payloads
            notif_messages = []
            for notif in events:
                formatted = self._format_notification(notif)
                notif_messages.append(formatted)
            combined_notif = "\n\n".join(notif_messages)

        if not combined_notif:
            return

        system_notif_msg = f"**Game Events:**\n\n{combined_notif}"

        # Add as user message so LLM sees it (system messages are filtered in some APIs)
        self.messages.append({"role": "user", "content": system_notif_msg})
        if self.trajectory:
            self.trajectory.notification(
                system_notif_msg,
                turn=self.turn_number,
                index=len(self.messages) - 1,
                events=[_event_payload(e) for e in events],
            )

        # Log to chat
        self._log_to_chat(f"**Game Events:**\n{combined_notif}\n\n")
        self._log_to_chat("---\n\n")

        # Display on console
        if hasattr(self.console, "system_notification"):
            self.console.system_notification(combined_notif)
        else:
            # Fallback if method doesn't exist yet
            print(f"\n📢 {combined_notif}\n")

    def _format_notification(self, notif: Dict[str, Any]) -> str:
        """Format notification as natural language message.

        Args:
            notif: Notification payload

        Returns:
            Formatted message string
        """
        ntype = notif.get("notification_type")
        data = notif.get("data", {})
        tick = notif.get("tick")

        if ntype == "research_finished":
            tech = data.get("technology")
            recipes = data.get("unlocked_recipes", [])
            recipes_str = ", ".join(recipes) if recipes else "none"
            return f"🔬 **Research Complete**: {tech}\n   Unlocked recipes: {recipes_str}\n   Game tick: {tick}"

        elif ntype == "research_started":
            tech = data.get("technology")
            return f"🔬 **Research Started**: {tech}\n   Game tick: {tick}"

        elif ntype == "research_cancelled":
            techs = list(data.get("technologies", {}).keys())
            techs_str = ", ".join(techs) if techs else "unknown"
            return f"🔬 **Research Cancelled**: {techs_str}\n   Game tick: {tick}"

        elif ntype == "research_queued":
            tech = data.get("technology")
            return f"🔬 **Research Queued**: {tech}\n   Game tick: {tick}"

        # Generic fallback
        return f"📢 **Game Event**: {ntype}\n   Data: {data}\n   Game tick: {tick}"

    def _estimate_token_count(self, messages: list) -> int:
        """
        Estimate token count for messages (rough approximation).

        Args:
            messages: List of message dicts

        Returns:
            Estimated token count
        """
        total_chars = 0
        for msg in messages:
            content = msg.get("content", "") or ""
            if content:
                total_chars += len(content)

            # Count tool calls if present
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                for tc in tool_calls:
                    total_chars += len(tc.get("function", {}).get("arguments", ""))

        # Rough estimate: 1 token ≈ 4 characters
        return total_chars // 4

    def _should_compress_context(self) -> bool:
        """
        Check if context should be compressed.

        Returns:
            True if approaching token limit
        """
        estimated_tokens = self._estimate_token_count(self.messages)
        threshold = int(self.max_context_tokens * 0.8)  # Compress at 80%
        return estimated_tokens > threshold

    def _check_and_compress_context(self):
        """
        Check if context needs compression and compress if needed.
        Preserves system prompt, initial state, and recent turns.
        """
        if not self._should_compress_context():
            return

        logger.info("Context approaching limit, compressing...")

        system_msg = (
            self.messages[0]
            if self.messages and self.messages[0].get("role") == "system"
            else None
        )
        initial_state_msg = None

        # Check if second message is initial state
        if len(self.messages) > 1:
            second_msg = self.messages[1]
            content = second_msg.get("content", "")
            if (
                second_msg.get("role") == "user"
                and "initial game state" in content.lower()
            ):
                initial_state_msg = second_msg
                conversation_start = 2
            else:
                conversation_start = 1
        else:
            conversation_start = 1

        # Get conversation messages (everything after system + initial state)
        conversation = self.messages[conversation_start:]

        if len(conversation) <= self.keep_recent_turns:
            logger.warning("Context large but not enough messages to compress")
            return

        # Keep recent messages
        recent_messages = conversation[-self.keep_recent_turns :]
        old_messages = conversation[: -self.keep_recent_turns]

        # Create summary of old messages
        summary_parts = []
        summary_parts.append(
            f"[Context Summary: {len(old_messages)} messages compressed]"
        )
        summary_parts.append(
            f"Turn range: 0-{self.turn_number - self.keep_recent_turns}"
        )

        # Extract key information from old messages
        user_requests = []
        tool_calls_count = 0

        for msg in old_messages:
            role = msg.get("role")
            content = msg.get("content", "") or ""
            tool_calls = msg.get("tool_calls")

            if role == "user":
                # Keep track of user requests
                content_preview = content[:100] if content else ""
                user_requests.append(content_preview)
            elif role == "assistant" and tool_calls:
                tool_calls_count += len(tool_calls)

        summary_parts.append(f"User requests: {len(user_requests)}")
        summary_parts.append(f"Tool calls executed: {tool_calls_count}")

        if user_requests:
            summary_parts.append("\nRecent requests (truncated):")
            for req in user_requests[-3:]:  # Last 3 requests
                summary_parts.append(f"- {req}...")

        summary_message = {"role": "user", "content": "\n".join(summary_parts)}

        # Rebuild messages list
        new_messages = []
        if system_msg:
            new_messages.append(system_msg)
        if initial_state_msg:
            new_messages.append(initial_state_msg)
        new_messages.append(summary_message)
        new_messages.extend(recent_messages)

        old_count = len(self.messages)
        self.messages = new_messages
        new_count = len(self.messages)

        logger.info(f"Context compressed: {old_count} -> {new_count} messages")
        if self.trajectory:
            self.trajectory.context_compressed(
                turn=self.turn_number,
                before_count=old_count,
                after_count=new_count,
                removed=old_messages,
                summary=summary_message,
            )

        # Log to chat if enabled
        if self.chat_log_path:
            with open(self.chat_log_path, "a") as f:
                f.write(
                    f"\n**System:** Context compressed ({old_count} -> {new_count} messages)\n\n"
                )
                f.write("---\n\n")

    def _calculate_fallback_usage(
        self, messages: list[Dict[str, Any]], completion_text: str
    ) -> Dict[str, int]:
        """Calculate fallback token usage using tiktoken."""
        try:
            encoding = tiktoken.encoding_for_model("gpt-4o")
        except KeyError:
            encoding = tiktoken.get_encoding("cl100k_base")

        prompt_tokens = 0
        for message in messages:
            # Approximate per-message overhead
            prompt_tokens += 3
            for key, value in message.items():
                if isinstance(value, str):
                    prompt_tokens += len(encoding.encode(value))
                elif isinstance(value, list):  # Tool calls
                    for item in value:
                        prompt_tokens += len(encoding.encode(str(item)))

        prompt_tokens += 3  # Reply primer

        completion_tokens = len(encoding.encode(completion_text))

        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }


def _event_payload(event: Any) -> Any:
    """Serialise a drained event for the record: typed events know how."""
    to_dict = getattr(event, "to_dict", None)
    if callable(to_dict):
        try:
            return to_dict()
        except Exception:
            pass
    if isinstance(event, dict):
        return event
    return repr(event)


# Backwards compatible alias
FactorioAgentOrchestrator = AgentOrchestrator
