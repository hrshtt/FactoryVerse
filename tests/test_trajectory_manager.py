"""Tests for trajectory manager."""

import pytest
from FactoryVerse.llm.trajectory_manager import TrajectoryManager, ActionStatus


def test_add_action():
    """Test adding actions to trajectory."""
    manager = TrajectoryManager()
    
    manager.add_action(
        tool_name="execute_dsl",
        arguments={"code": "print('hello')"},
        result="hello",
        compressed_result="hello",
        turn_number=0,
        status=ActionStatus.SUCCESS
    )
    
    assert len(manager.actions) == 1
    assert manager.actions[0].tool_name == "execute_dsl"


def test_get_statistics():
    """Test statistics calculation."""
    manager = TrajectoryManager()
    
    # Add some actions
    for i in range(10):
        status = ActionStatus.SUCCESS if i % 3 != 0 else ActionStatus.FAILURE
        manager.add_action(
            tool_name="execute_dsl",
            arguments={"code": f"action_{i}"},
            result="A" * 100,
            compressed_result="A" * 50,
            turn_number=i,
            status=status
        )
    
    stats = manager.get_statistics()
    
    assert stats["total_actions"] == 10
    assert stats["success_count"] == 7
    assert stats["failure_count"] == 3
    assert stats["avg_compression_ratio"] == 0.5
    assert stats["total_tokens_saved"] > 0


def test_prune_trajectory():
    """Test trajectory pruning."""
    manager = TrajectoryManager(max_history=5)
    
    # Add more actions than max_history
    for i in range(10):
        manager.add_action(
            tool_name="execute_dsl",
            arguments={"code": f"action_{i}"},
            result=f"result_{i}",
            compressed_result=f"result_{i}",
            turn_number=i,
            status=ActionStatus.SUCCESS
        )
    
    pruned = manager.prune_trajectory()
    
    assert pruned > 0
    assert len(manager.actions) <= manager.max_history


def test_prune_keeps_failures():
    """Test that pruning keeps failed actions."""
    manager = TrajectoryManager(max_history=5)
    
    # Add old failure
    manager.add_action(
        tool_name="execute_dsl",
        arguments={"code": "fail"},
        result="error",
        compressed_result="error",
        turn_number=0,
        status=ActionStatus.FAILURE
    )
    
    # Add many successful actions
    for i in range(10):
        manager.add_action(
            tool_name="execute_dsl",
            arguments={"code": f"action_{i}"},
            result=f"result_{i}",
            compressed_result=f"result_{i}",
            turn_number=i + 1,
            status=ActionStatus.SUCCESS
        )
    
    manager.prune_trajectory()
    
    # Check that the old failure is still there
    failure_actions = [a for a in manager.actions if a.status == ActionStatus.FAILURE]
    assert len(failure_actions) > 0


def test_get_context_for_llm():
    """Test context generation for LLM."""
    manager = TrajectoryManager(recent_full_output_count=3)
    
    # Add some actions
    for i in range(10):
        manager.add_action(
            tool_name="execute_dsl",
            arguments={"code": f"action_{i}"},
            result=f"full_result_{i}",
            compressed_result=f"compressed_{i}",
            turn_number=i,
            status=ActionStatus.SUCCESS
        )
    
    context = manager.get_context_for_llm()
    
    # Should have messages for all actions
    assert len(context) > 0


def test_auto_prune_on_threshold():
    """Test automatic pruning when threshold is exceeded."""
    manager = TrajectoryManager(max_history=5, prune_threshold=8)
    
    # Add actions up to threshold
    for i in range(9):
        manager.add_action(
            tool_name="execute_dsl",
            arguments={"code": f"action_{i}"},
            result=f"result_{i}",
            compressed_result=f"result_{i}",
            turn_number=i,
            status=ActionStatus.SUCCESS
        )
    
    # Should have auto-pruned
    assert len(manager.actions) <= manager.max_history


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
