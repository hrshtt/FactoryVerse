"""Task registry for looking up task configurations.

This module provides a singleton registry for all task definitions,
allowing lookup by task key and listing available tasks by category.
"""

import logging
from typing import Optional

from .base import TaskConfig, TaskType

logger = logging.getLogger(__name__)


class TaskRegistry:
    """Central registry for task configurations.

    Usage:
        registry = TaskRegistry.get()
        task = registry.get_task("iron_plate_throughput")
        all_tasks = registry.list_tasks()
    """

    _instance: Optional["TaskRegistry"] = None

    def __init__(self):
        """Initialize the registry. Use TaskRegistry.get() instead."""
        self._tasks: dict[str, TaskConfig] = {}
        self._loaded = False

    @classmethod
    def get(cls) -> "TaskRegistry":
        """Get the singleton registry instance.

        Loads all task definitions on first access.
        """
        if cls._instance is None:
            cls._instance = cls()
            cls._instance._load_all_tasks()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton instance.

        Useful for testing or when task definitions change.
        """
        cls._instance = None

    def _load_all_tasks(self) -> None:
        """Load all task definitions from the definitions package."""
        if self._loaded:
            return

        try:
            from .definitions import ALL_TASKS

            for task in ALL_TASKS:
                if task.task_key in self._tasks:
                    logger.warning(
                        f"Duplicate task key: {task.task_key}. "
                        "Later definition will override."
                    )
                self._tasks[task.task_key] = task

            self._loaded = True
            logger.info(f"Loaded {len(self._tasks)} tasks into registry")

        except ImportError as e:
            logger.error(f"Failed to import task definitions: {e}")
            self._loaded = True  # Mark as loaded to avoid repeated failures

    def get_task(self, task_key: str) -> TaskConfig:
        """Get a task configuration by key.

        Args:
            task_key: Unique task identifier

        Returns:
            TaskConfig for the requested task

        Raises:
            KeyError: If task_key doesn't exist
        """
        if task_key not in self._tasks:
            available = list(self._tasks.keys())[:5]
            raise KeyError(
                f"Unknown task: {task_key}. "
                f"Available: {', '.join(available)}... ({len(self._tasks)} total)"
            )
        return self._tasks[task_key]

    def task_exists(self, task_key: str) -> bool:
        """Check if a task exists in the registry.

        Args:
            task_key: Task identifier to check

        Returns:
            True if task exists
        """
        return task_key in self._tasks

    def list_tasks(self, task_type: Optional[TaskType] = None) -> list[str]:
        """List all available task keys.

        Args:
            task_type: Optional filter by task type

        Returns:
            List of task keys
        """
        if task_type is None:
            return list(self._tasks.keys())
        return [
            key
            for key, task in self._tasks.items()
            if task.task_type == task_type
        ]

    def list_tasks_by_type(self) -> dict[TaskType, list[str]]:
        """Get tasks organized by type.

        Returns:
            Dict mapping TaskType to list of task keys
        """
        result: dict[TaskType, list[str]] = {t: [] for t in TaskType}
        for key, task in self._tasks.items():
            result[task.task_type].append(key)
        return result

    def get_task_info(self, task_key: str) -> dict:
        """Get summary information about a task.

        Args:
            task_key: Task identifier

        Returns:
            Dict with task summary
        """
        task = self.get_task(task_key)
        info = {
            "task_key": task.task_key,
            "task_type": task.task_type.value,
            "goal_description": task.goal_description,
            "max_trajectory_steps": task.max_trajectory_steps,
            "all_technologies_researched": task.all_technologies_researched,
            "has_verification": task.verification is not None,
        }

        if task.verification:
            info["target_item"] = task.verification.target_item
            info["quota"] = task.verification.quota
            info["sustained_seconds"] = task.verification.sustained_seconds
            info["check_interval_seconds"] = task.verification.check_interval_seconds
            if task.verification.max_manual_ratio is not None:
                info["max_manual_ratio"] = task.verification.max_manual_ratio

        return info

    def register_task(self, task: TaskConfig) -> None:
        """Register a task configuration.

        Useful for dynamic task registration or testing.

        Args:
            task: TaskConfig to register
        """
        if task.task_key in self._tasks:
            logger.warning(f"Overwriting existing task: {task.task_key}")
        self._tasks[task.task_key] = task


# Convenience functions
def get_task(task_key: str) -> TaskConfig:
    """Get a task configuration by key."""
    return TaskRegistry.get().get_task(task_key)


def list_tasks(task_type: Optional[TaskType] = None) -> list[str]:
    """List all available task keys."""
    return TaskRegistry.get().list_tasks(task_type)


def task_exists(task_key: str) -> bool:
    """Check if a task exists in the registry."""
    return TaskRegistry.get().task_exists(task_key)
