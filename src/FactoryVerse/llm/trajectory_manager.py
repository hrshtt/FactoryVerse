"""Trajectory management for LLM agent action history."""

import time
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class ActionStatus(Enum):
    """Status of an action."""
    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"


@dataclass
class ActionRecord:
    """Record of a single action."""
    turn_number: int
    tool_name: str
    arguments: dict
    result: str  # Full result
    compressed_result: str  # Compressed result
    status: ActionStatus
    timestamp: float
    metadata: dict = field(default_factory=dict)


class TrajectoryManager:
    """Manage agent action history with compression."""
    
    def __init__(
        self,
        max_history: int = 50,
        recent_full_output_count: int = 10,
        prune_threshold: int = 100
    ):
        """
        Initialize trajectory manager.
        
        Args:
            max_history: Maximum actions to keep in memory
            recent_full_output_count: Number of recent actions to keep full output
            prune_threshold: Prune when action count exceeds this
        """
        self.max_history = max_history
        self.recent_full_output_count = recent_full_output_count
        self.prune_threshold = prune_threshold
        self.actions: List[ActionRecord] = []
    
    def add_action(
        self,
        tool_name: str,
        arguments: dict,
        result: str,
        compressed_result: str,
        turn_number: int,
        status: ActionStatus = ActionStatus.SUCCESS,
        metadata: Optional[dict] = None
    ) -> None:
        """
        Add action to trajectory.
        
        Args:
            tool_name: Name of tool executed
            arguments: Tool arguments
            result: Full result string
            compressed_result: Compressed result string
            turn_number: Current turn number
            status: Action status (success/failure/partial)
            metadata: Additional metadata
        """
        action = ActionRecord(
            turn_number=turn_number,
            tool_name=tool_name,
            arguments=arguments,
            result=result,
            compressed_result=compressed_result,
            status=status,
            timestamp=time.time(),
            metadata=metadata or {}
        )
        
        self.actions.append(action)
        
        # Auto-prune if threshold exceeded
        if len(self.actions) > self.prune_threshold:
            self.prune_trajectory()
    
    def get_context_for_llm(
        self,
        recent_count: Optional[int] = None,
        include_failures: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Get compressed trajectory for LLM context.
        
        Strategy:
        1. Keep last `recent_count` actions with full output
        2. Compress older actions (use compressed_result)
        3. Remove redundant successful actions
        4. Always keep failed actions if include_failures=True
        
        Args:
            recent_count: Number of recent actions with full output
                         (default: self.recent_full_output_count)
            include_failures: Always include failed actions
            
        Returns:
            List of message dicts for LLM context
        """
        recent_count = recent_count or self.recent_full_output_count
        
        if not self.actions:
            return []
        
        messages = []
        
        # Split into recent and older
        recent_actions = self.actions[-recent_count:]
        older_actions = self.actions[:-recent_count] if len(self.actions) > recent_count else []
        
        # Process older actions (compressed)
        for action in older_actions:
            # Skip redundant successful actions
            if action.status == ActionStatus.SUCCESS and self._is_redundant(action, older_actions):
                continue
            
            # Always include failures
            if action.status == ActionStatus.FAILURE and include_failures:
                messages.append(self._action_to_message(action, use_compressed=True))
            elif action.status != ActionStatus.FAILURE:
                messages.append(self._action_to_message(action, use_compressed=True))
        
        # Process recent actions (full output)
        for action in recent_actions:
            messages.append(self._action_to_message(action, use_compressed=False))
        
        return messages
    
    def _is_redundant(self, action: ActionRecord, action_list: List[ActionRecord]) -> bool:
        """
        Check if an action is redundant (repeated successful action).
        
        Heuristic: If there are multiple successful actions with the same tool_name
        and similar arguments, keep only the first and last.
        
        Args:
            action: Action to check
            action_list: List of actions to compare against
            
        Returns:
            True if action is redundant
        """
        # For now, simple heuristic: don't remove anything
        # This can be enhanced later with more sophisticated deduplication
        return False
    
    def _action_to_message(self, action: ActionRecord, use_compressed: bool) -> Dict[str, Any]:
        """
        Convert action record to message dict for LLM.
        
        Args:
            action: Action record
            use_compressed: Whether to use compressed result
            
        Returns:
            Message dict
        """
        result_text = action.compressed_result if use_compressed else action.result
        
        # Format as assistant message with tool call and tool response
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": f"call_{action.turn_number}_{action.tool_name}",
                "type": "function",
                "function": {
                    "name": action.tool_name,
                    "arguments": str(action.arguments)
                }
            }],
            "tool_responses": [{
                "tool_call_id": f"call_{action.turn_number}_{action.tool_name}",
                "role": "tool",
                "content": result_text
            }]
        }
    
    def prune_trajectory(self) -> int:
        """
        Remove expired/redundant actions.
        
        Pruning rules (AgentDiet-inspired):
        1. Remove successful actions older than max_history
        2. Keep failed actions for learning
        3. Remove redundant successful actions (e.g., repeated walks to same location)
        4. Keep actions that changed game state significantly
        
        Returns:
            Number of actions pruned
        """
        if len(self.actions) <= self.max_history:
            return 0
        
        # Keep recent actions
        recent_actions = self.actions[-self.max_history:]
        
        # From older actions, keep only failures
        older_actions = self.actions[:-self.max_history]
        kept_older = [a for a in older_actions if a.status == ActionStatus.FAILURE]
        
        pruned_count = len(self.actions) - len(recent_actions) - len(kept_older)
        
        # Update actions list
        self.actions = kept_older + recent_actions
        
        if pruned_count > 0:
            logger.info(f"Pruned {pruned_count} actions from trajectory")
        
        return pruned_count
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get trajectory statistics.
        
        Returns:
            Dict with:
            - total_actions: Total actions tracked
            - success_count: Number of successful actions
            - failure_count: Number of failed actions
            - avg_compression_ratio: Average compression ratio
            - total_tokens_saved: Estimated tokens saved by compression
        """
        if not self.actions:
            return {
                "total_actions": 0,
                "success_count": 0,
                "failure_count": 0,
                "partial_count": 0,
                "avg_compression_ratio": 0.0,
                "total_tokens_saved": 0
            }
        
        success_count = sum(1 for a in self.actions if a.status == ActionStatus.SUCCESS)
        failure_count = sum(1 for a in self.actions if a.status == ActionStatus.FAILURE)
        partial_count = sum(1 for a in self.actions if a.status == ActionStatus.PARTIAL)
        
        # Estimate compression ratio (chars as proxy for tokens)
        total_original = sum(len(a.result) for a in self.actions)
        total_compressed = sum(len(a.compressed_result) for a in self.actions)
        
        avg_compression_ratio = total_compressed / total_original if total_original > 0 else 1.0
        
        # Rough estimate: 1 token ≈ 4 characters
        tokens_saved = (total_original - total_compressed) // 4
        
        return {
            "total_actions": len(self.actions),
            "success_count": success_count,
            "failure_count": failure_count,
            "partial_count": partial_count,
            "avg_compression_ratio": avg_compression_ratio,
            "total_tokens_saved": tokens_saved
        }
