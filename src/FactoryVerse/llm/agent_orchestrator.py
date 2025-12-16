"""Simplified agent orchestrator for LLM-powered Factorio gameplay."""
import json
import logging
from typing import Optional, Dict, Any

from FactoryVerse.llm.client import PrimeIntellectClient
from FactoryVerse.agent_runtime import FactoryVerseRuntime
from FactoryVerse.llm.trajectory_manager import TrajectoryManager, ActionStatus
from FactoryVerse.llm.tool_validator import ToolValidator

logger = logging.getLogger(__name__)


class FactorioAgentOrchestrator:
    """Simple orchestrator for LLM agent gameplay."""
    
    def __init__(
        self,
        llm_client: PrimeIntellectClient,
        runtime: FactoryVerseRuntime,
        system_prompt_path: str = "factoryverse-system-prompt.md",
        chat_log_path: Optional[str] = None
    ):
        """
        Initialize orchestrator.
        
        Args:
            llm_client: LLM client
            runtime: Jupyter runtime
            system_prompt_path: Path to system prompt
            chat_log_path: Optional path to save chat log in markdown
        """
        self.llm_client = llm_client
        self.runtime = runtime
        self.trajectory_manager = TrajectoryManager()
        self.tool_validator = ToolValidator()
        self.turn_number = 0
        self.chat_log_path = chat_log_path
        
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
    
    async def run_turn(self, user_message: str) -> str:
        """
        Run one agent turn.
        
        Args:
            user_message: User's message
            
        Returns:
            Agent's text response
        """
        # Add user message
        self.messages.append({"role": "user", "content": user_message})
        
        tool_calls_executed = 0
        
        # Loop until agent responds with text (max 10 iterations)
        for iteration in range(1, 11):
            logger.info(f"Turn {self.turn_number}: Calling LLM (iteration {iteration})...")
            
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
                
                self.turn_number += 1
                return response_text
            
            # Execute tool calls
            logger.info(f"Turn {self.turn_number}: Executing {len(response.tool_calls)} tool calls...")
            
            for tool_call in response.tool_calls:
                tool_name = tool_call.function.name
                call_id = tool_call.id
                
                logger.info(f"  Tool: {tool_name}")
                
                try:
                    # Parse arguments
                    arguments = json.loads(tool_call.function.arguments)
                    
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
                    
                except json.JSONDecodeError as e:
                    result = f"❌ Invalid JSON arguments: {str(e)}"
                    status = ActionStatus.FAILURE
                except Exception as e:
                    result = f"❌ Execution error: {str(e)}"
                    status = ActionStatus.FAILURE
                
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
        
        # Max iterations reached
        logger.warning(f"Turn {self.turn_number}: Reached max iterations")
        self.turn_number += 1
        return "Max iterations reached. Please try a simpler request."
    
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
