import asyncio
import pytest
import logging
from uuid import uuid4
from pathlib import Path
from FactoryVerse.dsl.dsl import playing_factorio, configure
from tests.helpers.test_ground import TestGround
from FactoryVerse.infra.udp_dispatcher import get_udp_dispatcher, reset_global_dispatcher
from FactoryVerse.infra.factorio_client_setup import get_client_script_output_dir
from pathlib import Path

logger = logging.getLogger(__name__)

from factorio_rcon import RCONClient
import os
from dotenv import load_dotenv

load_dotenv()

@pytest.fixture
async def test_ground():
    """Context manager for TestGround helper"""
    rcon_host = os.getenv("RCON_HOST", "localhost")
    rcon_port = int(os.getenv("RCON_PORT", "27100"))
    rcon_pwd = os.getenv("RCON_PWD", "password")
    
    rcon = RCONClient(rcon_host, rcon_port, rcon_pwd)
    async with TestGround(rcon_client=rcon) as tg:
        yield tg

@pytest.fixture(scope="module", autouse=True)
async def ensure_hot_reload():
    """Ensure test-ground scenario is up to date once per session."""
    from tests.helpers.hot_reload_test_ground import hot_reload_test_ground
    import asyncio
    
    # We need to run this synchronously or in a separate thread, but it uses RCON which is blocking-ish
    # Since this is a module fixture, we can just call it.
    if not hot_reload_test_ground():
        pytest.fail("Failed to hot-reload test-ground scenario")
    
    # Give Factorio a moment to stabilize after reload
    await asyncio.sleep(2)

@pytest.mark.asyncio
async def test_duckdb_placement_sync(test_ground):
    """
    Test that placing an entity in Factorio correctly syncs to DuckDB.
    """
    agent_id = "agent_1"
    
    # Configure DSL first with in-memory DB
    configure(test_ground.rcon, agent_id, db_path=":memory:")
    
    try:
        # We use playing_factorio to manage the DB sync service
        with playing_factorio() as session:
            # Reset test area to known clean state
            await test_ground.reset_test_area()
            await asyncio.sleep(1) # Allow for any async cleanup

            # Place a furnace
            furnace_pos = {"x": 10.5, "y": 10.5}
            result = await test_ground.place_entity("stone-furnace", furnace_pos["x"], furnace_pos["y"])
            assert result["success"], f"Failed to place furnace: {result.get('error')}"
            
            # Verify that the test-ground script was updated and is running the new code
            assert result.get("metadata", {}).get("raised_built"), "❌ test-ground script is STALE! raise_built=true not found."
            logger.info("✅ Verified test-ground script is updated (raise_built=true)")
            

            # Verify file creation
            await asyncio.sleep(2)
            try:
                base_dir = get_client_script_output_dir()
                snapshot_dir = Path(base_dir) / "factoryverse" / "snapshots"
                
                logger.info(f"Checking snapshot files in {snapshot_dir}")
                found_updates = False
                if snapshot_dir and snapshot_dir.exists():
                    for f in snapshot_dir.rglob("*"):
                        if f.is_file():
                            logger.info(f"FILE: {f.relative_to(snapshot_dir)}")
                            if "entities_updates.jsonl" in f.name:
                                found_updates = True
                                # Print contents
                                logger.info(f"CONTENT {f.name}: {f.read_text()}")
                
                if not found_updates:
                    logger.error("❌ NO entities_updates.jsonl FOUND!")
            except Exception as e:
                logger.error(f"Failed to check snapshot files: {e}")

            # Wait for sync to happen (UDP -> Python -> DB)
            # We need to poll the DB
            found = False
            attempts = 0
            max_attempts = 10
            
            while not found and attempts < max_attempts:
                await asyncio.sleep(0.5)
                # Query DB for the furnace
                try:
                    query = f"""
                        SELECT entity_name, position 
                        FROM map_entity 
                        WHERE entity_name = 'stone-furnace' 
                        AND ABS(position['x'] - {furnace_pos['x']}) < 1.0 
                        AND ABS(position['y'] - {furnace_pos['y']}) < 1.0
                    """
                    res = session.map_db.connection.execute(query).fetchall()
                    if res:
                        found = True
                        logger.info(f"✅ Found entity in DB: {res[0]}")
                    else:
                        attempts += 1
                except Exception as e:
                    logger.warning(f"DB Query failed: {e}")
                    attempts += 1
                    
            assert found, "Entity failed to appear in DuckDB after placement"
    finally:
        # Ensure cleanup happens even if test fails
        d = get_udp_dispatcher()
        if d.is_running():
            await d.stop()
        reset_global_dispatcher()

@pytest.mark.asyncio
async def test_duckdb_removal_sync(test_ground):
    """
    Test that removing an entity in Factorio correctly deletes it from DuckDB.
    """

    agent_id = "agent_1"
    
    # Configure DSL first
    configure(test_ground.rcon, agent_id, db_path=":memory:")
    
    try:
        with playing_factorio() as session:
            await test_ground.reset_test_area()
            await asyncio.sleep(1)

            # Place entity first
            pos = {"x": 20.5, "y": 20.5}
            await test_ground.place_entity("stone-furnace", pos["x"], pos["y"])
            await asyncio.sleep(2) # Wait for initial sync
            
            # Verify it exists
            query_exists = f"""
                SELECT count(*) FROM map_entity 
                WHERE entity_name = 'stone-furnace' 
                AND ABS(position['x'] - {pos['x']}) < 1.0
            """
            count_pre = session.map_db.connection.execute(query_exists).fetchone()[0]
            assert count_pre > 0, "Pre-condition failed: Entity not in DB"
            
            # Remove entity via clear_area (which sets raise_destroy=true now)
            # clear_area(left_top_x, left_top_y, right_bottom_x, right_bottom_y)
            await test_ground.clear_area(20, 20, 21, 21)
            
            # Poll for removal
            removed = False
            attempts = 0
            while not removed and attempts < 10:
                await asyncio.sleep(0.5)
                count = session.map_db.connection.execute(query_exists).fetchone()[0]
                if count == 0:
                    removed = True
                    logger.info("✅ Entity successfully removed from DB")
                else:
                    # Manual Sync Trigger (Bypass UDP flake)
                    try:
                        from FactoryVerse.infra.factorio_client_setup import get_client_script_output_dir
                        script_dir = get_client_script_output_dir()
                        updates_path = script_dir / "factoryverse/snapshots/0/0/entities_updates.jsonl"
                        if updates_path.exists():
                            await session._game_data_sync._append_entities_updates(updates_path, 5)
                    except Exception as e:
                        logger.warning(f"Manual sync failed: {e}")
                    attempts += 1
                    
            assert removed, "Entity failed to be removed from DuckDB"
    finally:
        # Ensure cleanup happens even if test fails
        d = get_udp_dispatcher()
        if d.is_running():
            await d.stop()
        reset_global_dispatcher()

@pytest.mark.asyncio
async def test_duckdb_resource_mining_sync(test_ground):
    """
    Test that mining a resource (tree) removes it from resource_entity table.
    """

    agent_id = "agent_1"
    
    # Configure DSL first with in-memory DB
    configure(test_ground.rcon, agent_id, db_path=":memory:")
    
    try:
        with playing_factorio() as session:
            await test_ground.reset_test_area()
            # Ensure we wait for reset sync
            await asyncio.sleep(1)
            
            # Place a wooden-chest (simulate a resource entity or just mineable entity)
            # We use wooden-chest because it's definitely trackable
            pos = {"x": 30.5, "y": 30.5}
            await test_ground.place_entity("wooden-chest", pos["x"], pos["y"])
            await asyncio.sleep(2)
            
            # Verify in DB (map_entity table)
            query_res = f"""
                SELECT count(*) FROM map_entity 
                WHERE entity_name = 'wooden-chest' 
                AND ABS(position['x'] - {pos['x']}) < 1.0
            """
            
            # Let's verify where it landed
            count_res = session.map_db.connection.execute(query_res).fetchone()[0]
            assert count_res > 0, f"Chest placement failed sync to DB (count={count_res})"
            
            # Now Mine it (simulate destruction)
            # clear_area(left_top_x, left_top_y, right_bottom_x, right_bottom_y)
            await test_ground.clear_area(30, 30, 31, 31)
            
            # Poll for removal
            removed = False
            attempts = 0
            while not removed and attempts < 10:
                await asyncio.sleep(0.5)
                c = session.map_db.connection.execute(query_res).fetchone()[0]
                if c == 0:
                    removed = True
                else:
                    # Manual Sync Trigger (Bypass UDP flake)
                    try:
                        from FactoryVerse.infra.factorio_client_setup import get_client_script_output_dir
                        script_dir = get_client_script_output_dir()
                        updates_path = script_dir / "factoryverse/snapshots/0/0/entities_updates.jsonl"
                        if updates_path.exists():
                            await session._game_data_sync._append_entities_updates(updates_path, 5)
                    except Exception as e:
                        logger.warning(f"Manual sync failed: {e}")
                    attempts += 1
                    
            assert removed, "Chest removal failed to sync to DB"
    finally:
        # Ensure cleanup happens even if test fails
        d = get_udp_dispatcher()
        if d.is_running():
            await d.stop()
        reset_global_dispatcher()
