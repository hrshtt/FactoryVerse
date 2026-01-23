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
from FactoryVerse.infra.output.console import ConsoleOutput
from FactoryVerse.infra.session.trajectory import TrajectoryWriter

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

    def get_tool_definitions(self, mode: str = "autonomous") -> list:
        """Get tool definitions for LLM."""
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
        Run one agent turn.

        Args:
            user_message: User's message

        Returns:
            Agent's text response

        Raises:
            RuntimeError: If max_turns limit has been reached
        """
        # Check if we've reached max_turns
        if not self.has_turns_remaining():
            error_msg = f"Max turns limit reached ({self.max_turns} turns). Cannot execute more turns."
            logger.warning(error_msg)
            return error_msg

        # Log user message
        self._log_to_chat(f"**User:** {user_message}\n\n")
        self.console.user_message(user_message)
        if self.trajectory:
            self.trajectory.user_message(user_message, turn=self.turn_number)

        # Add user message
        self.messages.append({"role": "user", "content": user_message})

        tool_calls_executed = 0
        tool_results = []

        # Loop until agent responds with text (max 10 iterations)
        for iteration in range(1, 11):
            logger.info(
                f"Turn {self.turn_number}: Calling LLM (iteration {iteration})..."
            )
            self.console.llm_thinking(iteration)

            # Check and compress context if needed
            self._check_and_compress_context()

            # Call LLM - using new abstraction that returns ChatCompletionResult
            result = self.llm_client.chat_completion(
                messages=self.messages,
                tools=self.runtime.get_tool_definitions(mode=self.mode),
            )

            response: ChatMessage = result.message

            # Add response to messages (convert ChatMessage to dict)
            self.messages.append(response.to_dict())

            # Record token usage (with fallback)
            usage_data = None
            if result.usage:
                usage_data = {
                    "prompt_tokens": result.usage.prompt_tokens,
                    "completion_tokens": result.usage.completion_tokens,
                    "total_tokens": result.usage.total_tokens,
                }
            else:
                try:
                    usage_data = self._calculate_fallback_usage(
                        self.messages[
                            :-1
                        ],  # Prompt messages (excluding just added response)
                        response.content or "",
                    )
                except Exception as e:
                    logger.warning(f"Failed to calculate fallback token usage: {e}")

            if usage_data:
                # Write to trajectory file if available
                if self.trajectory:
                    self.trajectory.completion_stats(
                        turn=self.turn_number, usage=usage_data
                    )

                # Update in-memory trajectory manager for live viewer
                self.trajectory_manager.add_completion_stats(usage_data)

            # If no tool calls, return text response
            if not response.has_tool_calls:
                logger.info(f"Turn {self.turn_number}: Agent responded with text")

                # Check if response has content
                if not response.content or response.content.strip() == "":
                    logger.warning(
                        f"Turn {self.turn_number}: LLM returned empty content!"
                    )
                    response_text = "I apologize, I don't have a response. Could you rephrase your request?"
                else:
                    response_text = response.content

                self._log_to_chat(f"**Agent:** {response_text}\n\n")
                self._log_to_chat("---\n\n")
                self.console.assistant_response(response_text, self.turn_number)
                if self.trajectory:
                    self.trajectory.assistant_response(
                        response_text, turn=self.turn_number
                    )

                # Check for notifications after agent response (in case any arrived during LLM processing)
                await self._add_notifications_to_messages()

                self.console.turn_complete(self.turn_number)
                if self.trajectory:
                    self.trajectory.turn_complete(turn=self.turn_number)

                self.turn_number += 1
                return response_text

            # Execute tool calls
            tool_calls = response.tool_calls or []
            logger.info(
                f"Turn {self.turn_number}: Executing {len(tool_calls)} tool calls..."
            )

            # Log tool calls to chat BEFORE execution
            self._log_to_chat("<details>\n<summary>Tool calls</summary>\n\n")

            for tool_call in tool_calls:
                tool_name = tool_call.name
                call_id = tool_call.id

                logger.info(f"  Tool: {tool_name}")
                self.console.tool_call_start(tool_name, iteration)
                if self.trajectory:
                    self.trajectory.tool_start(
                        tool_name, turn=self.turn_number, iteration=iteration
                    )

                try:
                    # Parse arguments from the ToolCall
                    arguments = tool_call.parse_arguments()

                    # Log the tool call BEFORE execution
                    if tool_name == "execute_dsl":
                        self._log_to_chat(
                            f"**{tool_name}:**\n```python\n{arguments.get('code', '')}\n```\n\n"
                        )
                        self.console.tool_call_code(
                            arguments.get("code", ""), language="python"
                        )
                        if self.trajectory:
                            self.trajectory.tool_code(
                                arguments.get("code", ""),
                                turn=self.turn_number,
                                lang="python",
                            )
                    elif tool_name == "execute_duckdb":
                        self._log_to_chat(
                            f"**{tool_name}:**\n```sql\n{arguments.get('query', '')}\n```\n\n"
                        )
                        self.console.tool_call_code(
                            arguments.get("query", ""), language="sql"
                        )
                        if self.trajectory:
                            self.trajectory.tool_code(
                                arguments.get("query", ""),
                                turn=self.turn_number,
                                lang="sql",
                            )
                    else:
                        self._log_to_chat(
                            f"**{tool_name}:** {json.dumps(arguments, indent=2)}\n\n"
                        )

                    # Validate
                    validation = self.tool_validator.validate_tool_call(
                        tool_name, arguments
                    )

                    if not validation.valid:
                        exec_result = f"❌ Validation error: {validation.error}"
                        status = ActionStatus.FAILURE
                    else:
                        # Execute tool - parsed_arguments is guaranteed non-None when valid
                        parsed_args = validation.parsed_arguments or {}
                        exec_result, status = await self._execute_tool(
                            tool_name, parsed_args
                        )
                        tool_calls_executed += 1

                    # Log FULL result to chat.md (no truncation)
                    self._log_to_chat(f"**Result:**\n```\n{exec_result}\n```\n\n")

                    # Display result on console (console can truncate for readability)
                    is_error = exec_result.startswith("❌")
                    self.console.tool_result(exec_result, is_error=is_error)
                    if self.trajectory:
                        self.trajectory.tool_result(
                            exec_result, turn=self.turn_number, success=not is_error
                        )

                    # Track for final summary (use full result, not truncated)
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

                # Track in trajectory
                self.trajectory_manager.add_action(
                    tool_name=tool_name,
                    arguments=arguments if "arguments" in locals() else {},
                    result=exec_result,
                    compressed_result=exec_result,
                    turn_number=self.turn_number,
                    status=status,
                    metadata={"tool_call_id": call_id},
                )

                # Add tool response to messages
                self.messages.append(
                    {"role": "tool", "tool_call_id": call_id, "content": exec_result}
                )

                logger.info(
                    f"  Result: {exec_result[:100]}..."
                    if len(exec_result) > 100
                    else f"  Result: {exec_result}"
                )

                # Check for notifications right after tool execution completes
                # This ensures notifications generated during DSL/tool execution are immediately available
                await self._add_notifications_to_messages()

            # Close tool calls section in chat log
            self._log_to_chat("</details>\n\n")

            # Check task verification after tool execution
            # This runs the verification callback and injects progress into conversation
            verification_msg = await self._check_task_verification()
            if verification_msg:
                # Add verification progress as user message so agent sees it
                self.messages.append({"role": "user", "content": verification_msg})
                self._log_to_chat(f"**Task Progress:**\n```\n{verification_msg}\n```\n\n")
                self._log_to_chat("---\n\n")

                # Always display verification progress on console
                # This gives visibility into task progress during the run
                self.console.system_notification(verification_msg)

                if self._task_completed:
                    logger.info("AgentOrchestrator: Task completed via verification")
                    self.console.turn_complete(self.turn_number)
                    self.turn_number += 1
                    return "Task completed successfully!"
                else:
                    logger.debug(f"Task verification in progress: {self._last_verification_result}")

            # Special handling for respond tool - if used, return immediately
            if any(tc.name == "respond" for tc in tool_calls):
                # Find the respond tool result
                for tool_result in tool_results:
                    if tool_result["tool"] == "respond":
                        response_text = tool_result["result"]

                        # Log agent response
                        self._log_to_chat(f"**Agent:** {response_text}\n\n")
                        self._log_to_chat("---\n\n")
                        self.console.assistant_response(response_text, self.turn_number)

                        # Check for notifications
                        await self._add_notifications_to_messages()

                        self.console.turn_complete(self.turn_number)
                        self.turn_number += 1
                        return response_text

        # Max iterations reached
        logger.warning(f"Turn {self.turn_number}: Reached max iterations")
        self.console.max_iterations_warning(self.turn_number)
        self.console.turn_complete(self.turn_number)
        self.turn_number += 1
        return "Max iterations reached. Please try a simpler request."

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

        return "\n".join(lines)

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


# Backwards compatible alias
FactorioAgentOrchestrator = AgentOrchestrator
