"""Context management for DSL runtime.

This module handles the configuration and context management for the FactoryVerse DSL,
separating these concerns from the main API surface.
"""

from contextvars import ContextVar
from contextlib import contextmanager
from typing import Optional, Union
from pathlib import Path
import json
import logging
import sys
import asyncio

from factorio_rcon import RCONClient
from FactoryVerse.dsl.agent import PlayingFactory, _playing_factory
from FactoryVerse.dsl.recipe.base import Recipes


# Global configured factory instance
_configured_factory: Optional[PlayingFactory] = None


def enable_logging(level: int = logging.INFO):
    """
    Enable logging for the DSL to see RCON/UDP traffic.
    Useful in notebooks where default logging might be suppressed.
    
    Args:
        level: Logging level (default INFO)
    """
    # Get the library logger
    logger = logging.getLogger("src.FactoryVerse")
    logger.setLevel(level)
    
    # Check if handler already exists to avoid duplicates
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(
            '%(name)s - %(levelname)s - %(message)s'
        ))
        logger.addHandler(handler)


def configure(
    rcon_client: RCONClient, 
    agent_id: str,
    snapshot_dir: Optional[Path] = None,
    db_path: Optional[Union[str, Path]] = None,
    agent_udp_port: Optional[int] = None
):
    """
    Configure the DSL environment with RCON connection and agent ID.
    This should be called ONCE by the system/notebook initialization.
    
    Args:
        rcon_client: RCON client for remote interface calls
        agent_id: Agent ID (e.g., 'agent_1')
        snapshot_dir: Optional path to snapshot directory (auto-detected if None)
        db_path: Optional path to DuckDB database file (uses in-memory if None)
        agent_udp_port: Optional UDP port for agent-specific async actions. 
                       If provided, agent owns this port completely (decoupled from snapshot port).
    """
    global _configured_factory
    
    # 1. Fetch recipes
    cmd = f"/c rcon.print(helpers.table_to_json(remote.call('{agent_id}', 'get_recipes')))"
    try:
        res = rcon_client.send_command(cmd)
        res = rcon_client.send_command(cmd)
        recipes_data = json.loads(res)
        if isinstance(recipes_data, dict):
            # If it's a dict (keyed by name), convert to list of values
            recipes_data = list(recipes_data.values())
        recipes = Recipes(recipes_data)
        print(f"DEBUG: Loaded {len(recipes.recipes)} recipes into registry.")
    except Exception as e:
        print(f"Warning: Could not pre-fetch recipes: {e}")
        try:
             # Only print partial response if possible to avoid massive logs, or just type
            print(f"Recieved data type: {type(json.loads(res))}")
        except:
            pass
        recipes = Recipes({})

    # 2. Create and store factory instance
    # Note: RCON client is stored inside the factory but marked private
    # If agent_udp_port is provided, agent will listen directly on that port (decoupled from snapshot port)
    _configured_factory = PlayingFactory(rcon_client, agent_id, recipes, agent_udp_port=agent_udp_port)
    
    # 3. Auto-load snapshots if snapshot_dir or db_path provided
    # Note: Uses sync version here since configure() is not async
    # User should call await map_db.load_snapshots() in playing_factorio() context
    # to wait for initial snapshot completion
    if snapshot_dir is not None or db_path is not None:
        _configured_factory._load_snapshots_sync(
            snapshot_dir=snapshot_dir,
            db_path=db_path
        )


@contextmanager
def playing_factorio():
    """
    Context manager to activate the configured DSL runtime.
    
    Automatically starts GameDataSyncService if DB is loaded.
    The sync service runs in the background and keeps DB in sync.
    
    Usage:
        with playing_factorio():
            await walking.to(...)
            # DB is automatically synced before queries
            entities = map_db.connection.execute("SELECT * FROM map_entity").fetchall()
    """
    global _configured_factory
    
    if _configured_factory is None:
        raise RuntimeError(
            "DSL not configured. System must call dsl.configure(rcon, agent_id) first."
        )

    # Set context var to the pre-configured instance
    token = _playing_factory.set(_configured_factory)
    
    # Start game data sync service if DB is loaded (non-blocking)
    sync_started = False
    try:
        if _configured_factory._game_data_sync:
            # Start sync service in background if not already running
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Schedule start in background (non-blocking)
                    asyncio.create_task(_configured_factory._ensure_game_data_sync())
                    sync_started = True
                else:
                    # No loop running, start sync service
                    loop.run_until_complete(_configured_factory._ensure_game_data_sync())
                    sync_started = True
            except RuntimeError:
                # No event loop, create one and start sync
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(_configured_factory._ensure_game_data_sync())
                    sync_started = True
                except Exception as e:
                    logging.warning(f"Could not start game data sync service: {e}")
        
        yield _configured_factory
    finally:
        # Stop sync service if we started it
        if sync_started and _configured_factory._game_data_sync:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Schedule stop in background
                    asyncio.create_task(_configured_factory._stop_game_data_sync())
                else:
                    loop.run_until_complete(_configured_factory._stop_game_data_sync())
            except RuntimeError:
                pass
        
        _playing_factory.reset(token)


def get_current_factory() -> PlayingFactory:
    """
    Get the current playing factory context.
    
    Returns:
        PlayingFactory instance
        
    Raises:
        RuntimeError: If no active gameplay session
    """
    factory = _playing_factory.get()
    if factory is None:
        raise RuntimeError(
            "No active gameplay session. "
            "Use 'with playing_factorio():' to enable operations."
        )
    return factory
