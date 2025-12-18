"""Simplified agent orchestrator for LLM-powered Factorio gameplay."""
import json
import logging
import datetime
from typing import Optional, Dict, Any

from FactoryVerse.llm.client import PrimeIntellectClient
from FactoryVerse.agent_runtime import FactoryVerseRuntime
from FactoryVerse.llm.trajectory_manager import TrajectoryManager, ActionStatus
from FactoryVerse.llm.tool_validator import ToolValidator
from FactoryVerse.llm.console_output import ConsoleOutput

logger = logging.getLogger(__name__)


class FactorioAgentOrchestrator:
    """Simple orchestrator for LLM agent gameplay."""
    
    def __init__(
        self,
        llm_client: PrimeIntellectClient,
        runtime: FactoryVerseRuntime,
        system_prompt_path: str = "factoryverse-system-prompt.md",
        chat_log_path: Optional[str] = None,
        console_output: Optional[ConsoleOutput] = None,
        initial_state_path: Optional[str] = None,
        max_context_tokens: int = 100000,
        keep_recent_turns: int = 10
    ):
        """
        Initialize orchestrator.
        
        Args:
            llm_client: LLM client
            runtime: Jupyter runtime
            system_prompt_path: Path to system prompt
            chat_log_path: Optional path to save chat log in markdown
            console_output: Optional console output handler for clean display
            initial_state_path: Optional path to initial state markdown to inject as first message
            max_context_tokens: Maximum context window size before compression (default: 100k)
            keep_recent_turns: Number of recent turns to preserve during compression (default: 10)
        """
        self.llm_client = llm_client
        self.runtime = runtime
        self.trajectory_manager = TrajectoryManager()
        self.tool_validator = ToolValidator()
        self.turn_number = 0
        self.chat_log_path = chat_log_path
        self.console = console_output or ConsoleOutput(enabled=False)
        self.max_context_tokens = max_context_tokens
        self.keep_recent_turns = keep_recent_turns

        
        # Load system prompt
        try:
            with open(system_prompt_path, 'r') as f:
                system_prompt = f.read()
        except FileNotFoundError:
            logger.warning(f"System prompt not found: {system_prompt_path}")
            system_prompt = "You are a Factorio automation agent."
        
        self.messages = [{"role": "system", "content": system_prompt}]
        
        # Initialize chat log
        if self.chat_log_path:
            with open(self.chat_log_path, 'w') as f:
                f.write("# Factorio Agent Chat Log\n\n")
                f.write(f"Session started at {datetime.datetime.now().isoformat()}\n\n")
                f.write("---\n\n")
        
        # Inject initial state as first user message if provided
        if initial_state_path:
            try:
                with open(initial_state_path, 'r') as f:
                    initial_state = f.read()
                
                # Add as first user message
                self.messages.append({
                    "role": "user",
                    "content": f"Here is your initial game state:\n\n{initial_state}"
                })
                
                # Log to chat
                if self.chat_log_path:
                    with open(self.chat_log_path, 'a') as f:
                        f.write("**System:** Initial game state loaded\n\n")
                        f.write(f"<details>\n<summary>Initial State</summary>\n\n{initial_state}\n\n</details>\n\n")
                        f.write("---\n\n")
                
                logger.info(f"Injected initial state from {initial_state_path}")
            except FileNotFoundError:
                logger.warning(f"Initial state file not found: {initial_state_path}")
            except Exception as e:
                logger.error(f"Error loading initial state: {e}")

    
    async def run_turn(self, user_message: str) -> str:
        """
        Run one agent turn.
        
        Args:
            user_message: User's message
            
        Returns:
            Agent's text response
        """
        # Check for notifications FIRST (before processing user input)
        notifications = await self._check_notifications()
        
        if notifications:
            logger.info(f"Found {len(notifications)} pending notification(s)")
            
            # Format all notifications
            notif_messages = []
            for notif in notifications:
                formatted = self._format_notification(notif)
                notif_messages.append(formatted)
            
            # Combine into single system message
            combined_notif = "\n\n".join(notif_messages)
            system_notif_msg = f"**Game Notifications:**\n\n{combined_notif}"
            
            # Add as user message so LLM sees it (system messages are filtered in some APIs)
            self.messages.append({
                "role": "user",
                "content": system_notif_msg
            })
            
            # Log to chat
            self._log_to_chat(f"**System Notifications:**\n{combined_notif}\n\n")
            self._log_to_chat("---\n\n")
            
            # Display on console
            if hasattr(self.console, 'system_notification'):
                self.console.system_notification(combined_notif)
            else:
                # Fallback if method doesn't exist yet
                print(f"\n📢 {combined_notif}\n")
        
        # Log user message
        self._log_to_chat(f"**User:** {user_message}\n\n")
        self.console.user_message(user_message)
        
        # Add user message
        self.messages.append({"role": "user", "content": user_message})
        
        tool_calls_executed = 0
        tool_results = []
        
        # Loop until agent responds with text (max 10 iterations)
        for iteration in range(1, 11):
            logger.info(f"Turn {self.turn_number}: Calling LLM (iteration {iteration})...")
            self.console.llm_thinking(iteration)
            
            # Check and compress context if needed
            self._check_and_compress_context()
            
            # Call LLM
            response = self.llm_client.chat_completion(
                messages=self.messages,
                tools=self.runtime.get_tool_definitions()
            )
            
            # Add response to messages
            self.messages.append(response)
            
            # If no tool calls, return text response
            if not response.tool_calls:
                logger.info(f"Turn {self.turn_number}: Agent responded with text")
                
                # Check if response has content
                if not response.content or response.content.strip() == "":
                    logger.warning(f"Turn {self.turn_number}: LLM returned empty content!")
                    logger.warning(f"Response object: {response}")
                    response_text = "I apologize, I don't have a response. Could you rephrase your request?"
                else:
                    response_text = response.content
                
                # Log agent response
                self._log_to_chat(f"**Agent:** {response_text}\n\n")
                self._log_to_chat("---\n\n")
                self.console.assistant_response(response_text, self.turn_number)
                self.console.turn_complete(self.turn_number)
                
                self.turn_number += 1
                return response_text
            
            # Execute tool calls
            logger.info(f"Turn {self.turn_number}: Executing {len(response.tool_calls)} tool calls...")
            
            # Log tool calls to chat BEFORE execution
            self._log_to_chat("<details>\n<summary>Tool calls</summary>\n\n")
            
            for tool_call in response.tool_calls:
                tool_name = tool_call.function.name
                call_id = tool_call.id
                
                logger.info(f"  Tool: {tool_name}")
                self.console.tool_call_start(tool_name, iteration)
                
                try:
                    # Parse arguments
                    arguments = json.loads(tool_call.function.arguments)
                    
                    # Log the tool call BEFORE execution
                    if tool_name == "execute_dsl":
                        code_preview = arguments.get("code", "")[:200]
                        self._log_to_chat(f"**{tool_name}:**\n```python\n{arguments.get('code', '')}\n```\n\n")
                        self.console.tool_call_code(arguments.get('code', ''), language='python')
                    elif tool_name == "execute_duckdb":
                        self._log_to_chat(f"**{tool_name}:**\n```sql\n{arguments.get('query', '')}\n```\n\n")
                        self.console.tool_call_code(arguments.get('query', ''), language='sql')
                    else:
                        self._log_to_chat(f"**{tool_name}:** {json.dumps(arguments, indent=2)}\n\n")
                    
                    # Validate
                    validation = self.tool_validator.validate_tool_call(tool_name, arguments)
                    
                    if not validation.valid:
                        result = f"❌ Validation error: {validation.error}"
                        status = ActionStatus.FAILURE
                    else:
                        # Execute tool
                        result, status = await self._execute_tool(
                            tool_name,
                            validation.parsed_arguments
                        )
                        tool_calls_executed += 1
                    
                    # Log result immediately after execution
                    result_preview = result[:500] + "..." if len(result) > 500 else result
                    self._log_to_chat(f"**Result:**\n```\n{result_preview}\n```\n\n")
                    
                    # Display result on console
                    is_error = result.startswith("❌")
                    self.console.tool_result(result, is_error=is_error)
                    
                    # Track for final summary
                    tool_results.append({
                        'tool': tool_name,
                        'result': result_preview
                    })
            
                except json.JSONDecodeError as e:
                    result = f"❌ Invalid JSON arguments: {str(e)}"
                    status = ActionStatus.FAILURE
                    self._log_to_chat(f"**Error:** {result}\n\n")
                    self.console.tool_result(result, is_error=True)
                except Exception as e:
                    result = f"❌ Execution error: {str(e)}"
                    status = ActionStatus.FAILURE
                    self._log_to_chat(f"**Error:** {result}\n\n")
                    self.console.tool_result(result, is_error=True)
                
                # Track in trajectory
                self.trajectory_manager.add_action(
                    tool_name=tool_name,
                    arguments=arguments if 'arguments' in locals() else {},
                    result=result,
                    compressed_result=result,
                    turn_number=self.turn_number,
                    status=status,
                    metadata={"tool_call_id": call_id}
                )
                
                # Add tool response to messages
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": result
                })
                
                logger.info(f"  Result: {result[:100]}..." if len(result) > 100 else f"  Result: {result}")
            
            # Close tool calls section in chat log
            self._log_to_chat("</details>\n\n")
        
        # Max iterations reached
        logger.warning(f"Turn {self.turn_number}: Reached max iterations")
        self.console.max_iterations_warning(self.turn_number)
        self.console.turn_complete(self.turn_number)
        self.turn_number += 1
        return "Max iterations reached. Please try a simpler request."

    def _log_to_chat(self, message: str):
        """Append message to chat log file."""
        if self.chat_log_path:
            with open(self.chat_log_path, 'a') as f:
                f.write(message)
    
    async def _execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any]
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
            metadata = {
                "tool_name": tool_name,
                "turn_number": self.turn_number
            }
            
            if tool_name == "execute_dsl":
                result = self.runtime.execute_dsl(
                    arguments["code"],
                    metadata=metadata
                )
                return result, ActionStatus.SUCCESS
            
            elif tool_name == "execute_duckdb":
                result = self.runtime.execute_duckdb(
                    arguments["query"],
                    metadata=metadata
                )
                return result, ActionStatus.SUCCESS
            
            else:
                return f"❌ Unknown tool: {tool_name}", ActionStatus.FAILURE
        
        except Exception as e:
            logger.error(f"Error executing {tool_name}: {e}", exc_info=True)
            return f"❌ Execution error: {str(e)}", ActionStatus.FAILURE
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get trajectory statistics."""
        return self.trajectory_manager.get_statistics()
    
    async def _check_notifications(self) -> list[Dict[str, Any]]:
        """Check for pending game notifications.
        
        Returns:
            List of notification payloads
        """
        try:
            # Execute code in kernel to get notifications
            code = """
with playing_factorio():
    from FactoryVerse.dsl.dsl import _get_factory
    factory = _get_factory()
    notifications = await factory.get_notifications(timeout=0.1)
    print(json.dumps(notifications))
"""
            result = self.runtime.execute_code(code, compress_output=False)
            
            # Parse result
            if result and result.strip():
                import json
                notifications = json.loads(result.strip())
                return notifications if isinstance(notifications, list) else []
            return []
        except Exception as e:
            logger.warning(f"Error checking notifications: {e}")
            return []
    
    def _format_notification(self, notif: Dict[str, Any]) -> str:
        """Format notification as natural language message.
        
        Args:
            notif: Notification payload
            
        Returns:
            Formatted message string
        """
        ntype = notif.get('notification_type')
        data = notif.get('data', {})
        tick = notif.get('tick')
        
        if ntype == 'research_finished':
            tech = data.get('technology')
            recipes = data.get('unlocked_recipes', [])
            recipes_str = ', '.join(recipes) if recipes else 'none'
            return f"🔬 **Research Complete**: {tech}\n   Unlocked recipes: {recipes_str}\n   Game tick: {tick}"
        
        elif ntype == 'research_started':
            tech = data.get('technology')
            return f"🔬 **Research Started**: {tech}\n   Game tick: {tick}"
        
        elif ntype == 'research_cancelled':
            techs = list(data.get('technologies', {}).keys())
            techs_str = ', '.join(techs) if techs else 'unknown'
            return f"🔬 **Research Cancelled**: {techs_str}\n   Game tick: {tick}"
        
        elif ntype == 'research_queued':
            tech = data.get('technology')
            return f"🔬 **Research Queued**: {tech}\n   Game tick: {tick}"
        
        # Generic fallback
        return f"📢 **Game Event**: {ntype}\n   Data: {data}\n   Game tick: {tick}"
    
    def _estimate_token_count(self, messages: list) -> int:
        """
        Estimate token count for messages (rough approximation).
        
        Args:
            messages: List of message dicts or ChatCompletionMessage objects
            
        Returns:
            Estimated token count
        """
        total_chars = 0
        for msg in messages:
            # Handle both dict and Pydantic object
            if isinstance(msg, dict):
                content = msg.get("content", "")
                tool_calls = msg.get("tool_calls")
            else:
                # Pydantic ChatCompletionMessage object
                content = getattr(msg, "content", "") or ""
                tool_calls = getattr(msg, "tool_calls", None)
            
            if content:
                total_chars += len(content)
            
            # Count tool calls if present
            if tool_calls:
                for tc in tool_calls:
                    if isinstance(tc, dict):
                        total_chars += len(tc.get("function", {}).get("arguments", ""))
                    else:
                        # Pydantic object
                        func = getattr(tc, "function", None)
                        if func:
                            args = getattr(func, "arguments", "") or ""
                            total_chars += len(args)
        
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
        
        # Separate messages by type
        # Handle both dict and Pydantic objects
        def get_role(msg):
            return msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", None)
        
        def get_content(msg):
            if isinstance(msg, dict):
                return msg.get("content", "")
            return getattr(msg, "content", "") or ""
        
        system_msg = self.messages[0] if self.messages and get_role(self.messages[0]) == "system" else None
        initial_state_msg = None
        
        # Check if second message is initial state
        if len(self.messages) > 1:
            second_msg = self.messages[1]
            if get_role(second_msg) == "user" and "initial game state" in get_content(second_msg).lower():
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
        recent_messages = conversation[-self.keep_recent_turns:]
        old_messages = conversation[:-self.keep_recent_turns]
        
        # Create summary of old messages
        summary_parts = []
        summary_parts.append(f"[Context Summary: {len(old_messages)} messages compressed]")
        summary_parts.append(f"Turn range: 0-{self.turn_number - self.keep_recent_turns}")
        
        # Extract key information from old messages
        user_requests = []
        tool_calls_count = 0
        
        for msg in old_messages:
            # Handle both dict and Pydantic object
            if isinstance(msg, dict):
                role = msg.get("role")
                content = msg.get("content", "")
                tool_calls = msg.get("tool_calls")
            else:
                role = getattr(msg, "role", None)
                content = getattr(msg, "content", "") or ""
                tool_calls = getattr(msg, "tool_calls", None)
            
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
        
        summary_message = {
            "role": "user",
            "content": "\n".join(summary_parts)
        }
        
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
            with open(self.chat_log_path, 'a') as f:
                f.write(f"\n**System:** Context compressed ({old_count} -> {new_count} messages)\n\n")
                f.write("---\n\n")
