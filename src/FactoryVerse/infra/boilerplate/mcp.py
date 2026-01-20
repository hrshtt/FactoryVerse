"""MCP-specific utilities for boilerplate sessions.

Provides high-level functions for MCP server to manage sessions,
execute code, and interact with FactoryVerse environments.

Usage in MCP server:
    from FactoryVerse.infra.boilerplate.mcp import (
        mcp_create_session,
        mcp_execute_code,
        mcp_reload_session,
    )

    result = await mcp_create_session('dev_1', scope=Scope.RUNTIME)
    result = await mcp_execute_code('dev_1', 'print(runtime.agent_id)')
"""

import asyncio
from pathlib import Path
from typing import Optional, Dict, Any

from . import (
    Scope,
    create_session,
    get_session,
    list_sessions,
    destroy_session,
    destroy_all_sessions,
)


async def mcp_create_session(
    session_id: str,
    scope: Scope = Scope.RUNTIME,
    instance: Optional[str] = None,
    agent_id: str = "agent_1",
    session_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a new boilerplate session.

    Args:
        session_id: Unique session identifier
        scope: Which scope to load (RCON, SNAPSHOT, AGENT, RUNTIME)
        instance: Factorio instance ('client' or 'server_N')
        agent_id: Agent identifier
        session_dir: Session directory path (optional)

    Returns:
        Dict with session info and status
    """
    try:
        session = create_session(
            session_id=session_id,
            scope=scope,
            instance=instance,
            agent_id=agent_id,
            session_dir=Path(session_dir) if session_dir else None,
        )

        # Start the session
        await session.start()

        ctx = session.ctx

        return {
            "success": True,
            "session_id": session_id,
            "scope": scope.name,
            "instance": ctx.instance.name if ctx.instance else None,
            "agent_id": ctx.agent_id,
            "components": list(ctx.keys()),
        }

    except ValueError as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": "session_exists",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
        }


async def mcp_execute_code(
    session_id: str,
    code: str,
) -> Dict[str, Any]:
    """Execute Python code in a session context.

    The code has access to all session components as globals.

    Args:
        session_id: Session to execute in
        code: Python code to execute

    Returns:
        Dict with execution result or error
    """
    session = get_session(session_id)
    if session is None:
        return {
            "success": False,
            "error": f"Session '{session_id}' not found",
            "error_type": "session_not_found",
        }

    try:
        ctx = session.ctx

        # Build globals from context
        exec_globals = dict(ctx._components)
        exec_globals["__builtins__"] = __builtins__

        # Add async support
        exec_globals["asyncio"] = asyncio

        # =================================================================
        # Import all types documented in API reference for agent use
        # =================================================================
        from FactoryVerse.factory.types import (
            MapPosition,
            Direction,
            BoundingBox,
            CraftingQueueStatus,
            ResearchQueueItem,
        )
        from FactoryVerse.agent.placement_hints import (
            ConnectionType,
            ConnectionPosition,
            WireConnectionPosition,
            GhostPlan,
            PolePlacementResult,
            EntityValidationError,
        )
        from FactoryVerse.factory.item.base import (
            Item,
            PlaceableItem,
            ItemStack,
        )
        from FactoryVerse.agent.embodied_actions.walking import (
            WalkingError,
            WalkingUnreachableError,
            WalkingEntityNotFoundError,
            WalkingNoStandableTilesError,
        )
        from FactoryVerse.agent.embodied_actions.research import (
            ResearchStatus,
            QueuedTechnology,
        )

        # Add all types to exec globals
        exec_globals.update({
            # Core spatial types
            "MapPosition": MapPosition,
            "Direction": Direction,
            "BoundingBox": BoundingBox,
            # Placement types
            "ConnectionType": ConnectionType,
            "ConnectionPosition": ConnectionPosition,
            "WireConnectionPosition": WireConnectionPosition,
            "GhostPlan": GhostPlan,
            "PolePlacementResult": PolePlacementResult,
            "EntityValidationError": EntityValidationError,
            # Item types
            "Item": Item,
            "PlaceableItem": PlaceableItem,
            "ItemStack": ItemStack,
            # Status types
            "CraftingQueueStatus": CraftingQueueStatus,
            "ResearchStatus": ResearchStatus,
            "ResearchQueueItem": ResearchQueueItem,
            "QueuedTechnology": QueuedTechnology,
            # Walking exceptions
            "WalkingError": WalkingError,
            "WalkingUnreachableError": WalkingUnreachableError,
            "WalkingEntityNotFoundError": WalkingEntityNotFoundError,
            "WalkingNoStandableTilesError": WalkingNoStandableTilesError,
        })

        # Check if code contains await
        if "await " in code:
            # Wrap in async function and execute
            # Build the wrapped code with proper indentation
            indented_lines = "\n".join("    " + line for line in code.split("\n"))
            wrapped_code = f"""
async def __mcp_async_exec__():
{indented_lines}
"""
            exec(wrapped_code, exec_globals)
            async_func = exec_globals["__mcp_async_exec__"]
            # Run the async function - await properly since we're already async
            result = await async_func()
        else:
            # Execute synchronously
            exec(code, exec_globals)
            result = None

        return {
            "success": True,
            "session_id": session_id,
            "result": str(result) if result is not None else None,
        }

    except Exception as e:
        import traceback

        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
            "traceback": traceback.format_exc(),
        }


async def mcp_reload_session(
    session_id: str,
    reload_lua: bool = False,
) -> Dict[str, Any]:
    """Reload a session.

    Args:
        session_id: Session to reload
        reload_lua: Also reload Factorio Lua scripts

    Returns:
        Dict with reload status
    """
    session = get_session(session_id)
    if session is None:
        return {
            "success": False,
            "error": f"Session '{session_id}' not found",
            "error_type": "session_not_found",
        }

    try:
        await session.reload(reload_lua=reload_lua)

        ctx = session.ctx

        return {
            "success": True,
            "session_id": session_id,
            "lua_reloaded": reload_lua,
            "scope": session.scope.name,
            "components": list(ctx.keys()),
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
        }


async def mcp_destroy_session(session_id: str) -> Dict[str, Any]:
    """Destroy a session.

    Args:
        session_id: Session to destroy

    Returns:
        Dict with destruction status
    """
    destroyed = await destroy_session(session_id)

    return {
        "success": destroyed,
        "session_id": session_id,
        "error": None if destroyed else f"Session '{session_id}' not found",
    }


async def mcp_list_sessions() -> Dict[str, Any]:
    """List all active sessions.

    Returns:
        Dict with session info
    """
    sessions = list_sessions()

    session_info = []
    for session_id, session in sessions.items():
        session_info.append(
            {
                "session_id": session_id,
                "scope": session.scope.name,
                "instance": session.instance,
                "agent_id": session.agent_id,
            }
        )

    return {
        "success": True,
        "count": len(session_info),
        "sessions": session_info,
    }


async def mcp_destroy_all_sessions() -> Dict[str, Any]:
    """Destroy all active sessions.

    Returns:
        Dict with destruction count
    """
    count = await destroy_all_sessions()

    return {
        "success": True,
        "destroyed_count": count,
    }


# Export convenience functions that match MCP tool patterns
__all__ = [
    "mcp_create_session",
    "mcp_execute_code",
    "mcp_reload_session",
    "mcp_destroy_session",
    "mcp_list_sessions",
    "mcp_destroy_all_sessions",
]
