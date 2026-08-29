"""Session management for FactoryVerse Environment.

Provides a registry of named Environment instances for MCP and development workflows.
Replaces the boilerplate session management with Environment-based approach.

Usage:
    >>> from FactoryVerse.environment.sessions import (
    ...     create_session, get_session, destroy_session
    ... )
    >>>
    >>> # Create a session initialized to RUNTIME tier
    >>> env = await create_session("dev_1", up_to=Tier.RUNTIME)
    >>>
    >>> # Access components
    >>> env.tier3.rcon.send_command('/c print("hello")')
    >>> env.tier4.entity_reference("transport-belt").can_place(...)
    >>>
    >>> # Destroy when done
    >>> await destroy_session("dev_1")
"""

import asyncio
import logging
from typing import Dict, Optional, List, Any

from .environment import Environment, Tier
from .config import EnvironmentConfig, RuntimeVariant

logger = logging.getLogger(__name__)

# Module-level session registry
_sessions: Dict[str, Environment] = {}


async def create_session(
    session_id: str,
    up_to: Tier = Tier.RUNTIME,
    scenario: str = "test-ground",
    instance: Optional[str] = None,
    agent_id: str = "agent_1",
    variant: RuntimeVariant = RuntimeVariant.MINIMAL,
    initial_inventory: Optional[Dict[str, int]] = None,
) -> Environment:
    """Create a new managed Environment session.

    Args:
        session_id: Unique identifier for the session
        up_to: Tier to initialize up to (default: RUNTIME)
        scenario: Scenario to use (default: test-ground)
        instance: Factorio instance ('client' or 'server_N'), auto-detect if None
        agent_id: Agent identifier (default: agent_1)
        variant: Runtime variant (default: MINIMAL for speed)
        initial_inventory: Initial inventory items {item_name: count, ...}

    Returns:
        Initialized Environment instance

    Raises:
        ValueError: If session_id already exists
        TierInitializationError: If initialization fails
    """
    if session_id in _sessions:
        raise ValueError(f"Session '{session_id}' already exists")

    # Create config
    from .config import PythonConfig, RuntimeConfig, SettingsConfig

    config = EnvironmentConfig(
        tier2=SettingsConfig(scenario=scenario),
        tier3=PythonConfig(instance=instance, agent_id=agent_id),
        tier4=RuntimeConfig(variant=variant, agent_id=agent_id, initial_inventory=initial_inventory),
    )

    env = Environment(config=config)

    try:
        await env.initialize(up_to=up_to)
        _sessions[session_id] = env
        logger.info(f"Session '{session_id}' created, initialized to {up_to.name}")
        return env
    except Exception as e:
        # Clean up on failure
        try:
            await env.shutdown()
        except Exception:
            pass
        raise


def get_session(session_id: str) -> Optional[Environment]:
    """Get an existing session by ID.

    Args:
        session_id: Session identifier

    Returns:
        Environment instance or None if not found
    """
    return _sessions.get(session_id)


def list_sessions() -> Dict[str, Dict[str, Any]]:
    """List all active sessions with their status.

    Returns:
        Dict mapping session_id to session info
    """
    result = {}
    for session_id, env in _sessions.items():
        result[session_id] = {
            "session_id": session_id,
            "initialized_up_to": env._initialized_up_to.name if env._initialized_up_to else None,
            "agent_id": env.config.tier4.agent_id if env.config.tier4 else None,
            "scenario": env.config.tier2.scenario if env.config.tier2 else None,
        }
    return result


async def destroy_session(session_id: str) -> bool:
    """Destroy a session and cleanup resources.

    Args:
        session_id: Session identifier

    Returns:
        True if session was destroyed, False if not found
    """
    env = _sessions.pop(session_id, None)
    if env is not None:
        try:
            await env.shutdown()
            logger.info(f"Session '{session_id}' destroyed")
        except Exception as e:
            logger.warning(f"Error shutting down session '{session_id}': {e}")
        return True
    return False


async def destroy_all_sessions() -> int:
    """Destroy all active sessions.

    Returns:
        Number of sessions destroyed
    """
    count = len(_sessions)
    session_ids = list(_sessions.keys())

    for session_id in session_ids:
        await destroy_session(session_id)

    return count


async def reload_session(
    session_id: str,
    reload_lua: bool = False,
    from_tier: Tier = Tier.RUNTIME,
) -> Environment:
    """Reload a session to pick up code changes.

    This will:
    1. Reset tiers from specified tier upward
    2. Optionally reload Factorio Lua scripts
    3. Re-initialize the reset tiers

    Args:
        session_id: Session to reload
        reload_lua: Also trigger Factorio script reload via RCON
        from_tier: Tier to reset from (default: RUNTIME)

    Returns:
        The reloaded Environment

    Raises:
        ValueError: If session not found
    """
    env = _sessions.get(session_id)
    if env is None:
        raise ValueError(f"Session '{session_id}' not found")

    # Optionally reload Lua
    if reload_lua and env.tier3 and env.tier3.rcon:
        try:
            env.tier3.rcon.send_command(
                "/c game.reload_script();game.print('Scripts reloaded')"
            )
            logger.info(f"Session '{session_id}': Lua scripts reloaded")
        except Exception as e:
            logger.warning(f"Failed to reload Lua scripts: {e}")

    # Reset and re-initialize
    original_tier = env._initialized_up_to
    await env.reset(from_tier=from_tier)

    if original_tier:
        await env.initialize(up_to=original_tier)

    logger.info(f"Session '{session_id}' reloaded from {from_tier.name}")
    return env


def get_session_components(session_id: str) -> Dict[str, Any]:
    """Get dict of components from a session for code execution.

    Provides flat dict access to common components for convenience.
    This is used by MCP code execution to inject components into namespace.

    Args:
        session_id: Session identifier

    Returns:
        Dict with component names as keys

    Raises:
        ValueError: If session not found
    """
    env = _sessions.get(session_id)
    if env is None:
        raise ValueError(f"Session '{session_id}' not found")

    components = {}

    # Tier 3 components
    if env.tier3:
        components["rcon"] = env.tier3.rcon
        components["instance"] = env.tier3.instance

    # Tier 4 components
    if env.tier4:
        components["database"] = env.tier4.database
        components["remote_view"] = env.tier4.remote_view
        components["reachable_view"] = env.tier4.reachable_view
        components["entity_reference"] = env.tier4.entity_reference

        # Embodied actions (if available) - stored as dict in tier4
        ea = env.tier4.embodied_actions
        if ea:
            # tier4 stores these as a dict with specific keys
            components["walking"] = ea.get("movement")
            components["crafting"] = ea.get("crafting")
            components["research"] = ea.get("research")
            components["inventory"] = ea.get("inventory")

        # Runtime for backward compat
        components["runtime"] = ea

    return components


__all__ = [
    "create_session",
    "get_session",
    "list_sessions",
    "destroy_session",
    "destroy_all_sessions",
    "reload_session",
    "get_session_components",
]
