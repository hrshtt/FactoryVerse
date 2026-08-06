import duckdb
import pytest

from FactoryVerse.game.agent.remote_view import RemoteView


@pytest.mark.asyncio
async def test_remote_view_checkpoint_copies_in_memory_database(tmp_path):
    view = RemoteView(
        snapshot_dir=tmp_path / "snapshots",
        entity_ops=None,
        place_ops=None,
        walking_action=None,
        mining_action=None,
    )
    await view.load(wait_for_bootstrap=False)
    view._database.connection.execute(
        """
        INSERT INTO map_entity (
            entity_name, position_x, position_y, chunk_x, chunk_y, direction, force
        ) VALUES ('stone-furnace', 1.5, 2.5, 0, 0, 'NORTH', 'player')
        """
    )

    fingerprint = view.state_fingerprint()
    destination = view.checkpoint_database(tmp_path / "checkpoint.duckdb")

    assert fingerprint["entity_count"] == 1
    with duckdb.connect(str(destination), read_only=True) as connection:
        assert connection.execute("SELECT count(*) FROM map_entity").fetchone()[0] == 1

    await view.stop()


@pytest.mark.asyncio
async def test_remote_view_checkpoint_copies_file_backed_database(tmp_path):
    view = RemoteView(
        snapshot_dir=tmp_path / "snapshots",
        entity_ops=None,
        place_ops=None,
        walking_action=None,
        mining_action=None,
        db_path=tmp_path / "runtime.duckdb",
    )
    await view.load(wait_for_bootstrap=False)
    view._database.connection.execute(
        """
        INSERT INTO map_entity (
            entity_name, position_x, position_y, chunk_x, chunk_y, direction, force
        ) VALUES ('assembling-machine-1', 3.5, 4.5, 0, 0, 'EAST', 'player')
        """
    )

    destination = view.checkpoint_database(tmp_path / "checkpoint.duckdb")

    with duckdb.connect(str(destination), read_only=True) as connection:
        tables = {row[0] for row in connection.execute("SHOW TABLES").fetchall()}
        assert "map_entity" in tables
        assert connection.execute("SELECT count(*) FROM map_entity").fetchone()[0] == 1

    await view.stop()
