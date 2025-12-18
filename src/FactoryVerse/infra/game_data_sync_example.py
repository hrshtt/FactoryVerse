"""
Example usage of GameDataSyncService in an agent notebook runtime.

This demonstrates the per-agent pattern where each agent has its own:
- DuckDB database
- GameDataSyncService instance
- RCON client
"""

import asyncio
import duckdb
from pathlib import Path
from factorio_rcon import RCONClient

from FactoryVerse.infra.game_data_sync import GameDataSyncService
from FactoryVerse.infra.udp_dispatcher import get_udp_dispatcher


async def agent_runtime_example():
    """Example agent runtime setup and usage."""
    
    # ============================================================================
    # Agent-specific setup
    # ============================================================================
    agent_id = "agent_1"
    db_path = f"agent_{agent_id}.db"
    snapshot_dir = Path("script-output/factoryverse/snapshots")
    rcon_port = 34200
    rcon_password = "factorio"
    
    # Create agent's DuckDB database
    db = duckdb.connect(db_path)
    
    # Create RCON client
    rcon_client = RCONClient("localhost", rcon_port, rcon_password)
    
    # Get shared UDP dispatcher (or create if first agent)
    udp_dispatcher = get_udp_dispatcher()
    
    # ============================================================================
    # Create and start GameDataSyncService
    # ============================================================================
    sync_service = GameDataSyncService(
        agent_id=agent_id,
        db_connection=db,
        snapshot_dir=snapshot_dir,
        udp_dispatcher=udp_dispatcher,
        rcon_client=rcon_client,
    )
    
    # Start background sync service
    await sync_service.start()
    
    try:
        # ============================================================================
        # Example 1: Pre-query sync pattern (CRITICAL)
        # ============================================================================
        print("Example 1: Pre-query sync")
        
        # Before ANY DB query, ensure DB is synced
        await sync_service.ensure_synced()
        
        # Now safe to query (write lock ensures no concurrent writes)
        result = db.execute("SELECT COUNT(*) as count FROM map_entity").fetchone()
        print(f"Entity count: {result[0] if result else 0}")
        
        # ============================================================================
        # Example 2: Wait for chunk snapshot
        # ============================================================================
        print("\nExample 2: Wait for chunk snapshot")
        
        chunk_x, chunk_y = 5, 3
        
        # Check current state
        state = sync_service.get_snapshot_state(chunk_x, chunk_y)
        print(f"Chunk ({chunk_x}, {chunk_y}) state: {state}")
        
        # Wait for snapshot to complete
        if state != "COMPLETE":
            print(f"Waiting for chunk ({chunk_x}, {chunk_y}) snapshot to complete...")
            await sync_service.wait_for_chunk_snapshot(chunk_x, chunk_y, timeout=30.0)
            print("Chunk snapshot completed!")
        
        # Ensure sync before querying
        await sync_service.ensure_synced()
        
        # Query entities in chunk
        entities = db.execute(
            "SELECT * FROM map_entity WHERE chunk_x = ? AND chunk_y = ?",
            [chunk_x, chunk_y]
        ).fetchall()
        print(f"Found {len(entities)} entities in chunk ({chunk_x}, {chunk_y})")
        
        # ============================================================================
        # Example 3: Action awaiting
        # ============================================================================
        print("\nExample 3: Action awaiting")
        
        action_id = "walk_to_123"
        
        # Register action
        sync_service.register_action(action_id)
        
        # Send RCON command
        rcon_command = f"/c remote.call('{agent_id}', 'walk_to', {{x=10, y=20}})"
        rcon_client.send_command(rcon_command)
        
        # Wait for completion
        print(f"Waiting for action {action_id} to complete...")
        result = await sync_service.wait_for_action(action_id, timeout=30.0)
        print(f"Action completed: {result.get('status')}")
        
        # ============================================================================
        # Example 4: Context manager pattern (recommended)
        # ============================================================================
        print("\nExample 4: Context manager pattern")
        
        from contextlib import asynccontextmanager
        
        @asynccontextmanager
        async def db_query_context(sync_service: GameDataSyncService):
            """Context manager that ensures sync before query."""
            await sync_service.ensure_synced()
            yield
            # Lock is released automatically
        
        # Usage
        async with db_query_context(sync_service):
            entities = db.execute("SELECT * FROM map_entity LIMIT 10").fetchall()
            print(f"Queried {len(entities)} entities (DB guaranteed to be synced)")
        
    finally:
        # Cleanup
        await sync_service.stop()
        db.close()
        print("\n✅ Agent runtime stopped")


if __name__ == "__main__":
    asyncio.run(agent_runtime_example())

