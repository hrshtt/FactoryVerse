"""Snapshot scope loader - Scope.SNAPSHOT

This module adds snapshot loading and DuckDB database support.
Builds on RCON scope.

Components loaded (in addition to RCON):
    - snapshot_dir: Path to snapshot directory
    - db_path: Path to DuckDB file
    - database: SnapshotDatabase wrapper
    - snapshot_loader: SnapshotLoader instance

Usage:
    >>> from FactoryVerse.infra.llm.boilerplate import load, Scope
    >>> ctx = load(scope=Scope.SNAPSHOT)
    >>> result = ctx['database'].connection.execute("SELECT * FROM entities LIMIT 10")
"""

import os
from pathlib import Path
from typing import Optional, Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from . import BoilerplateContext


def load_snapshot_scope(
    ctx: "BoilerplateContext",
    session_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Load snapshot scope components.

    Requires RCON scope to be loaded first.

    Args:
        ctx: BoilerplateContext with RCON scope loaded
        session_dir: Session directory for DB file, defaults to cwd

    Returns:
        Dict with: snapshot_dir, db_path, database, snapshot_loader
    """
    from FactoryVerse.agent.snapshot.loader import SnapshotLoader
    from FactoryVerse.agent.snapshot.database import SnapshotDatabase

    instance = ctx["instance"]
    config = ctx["config"]
    rcon = ctx["rcon"]

    # Session directory for artifacts
    if session_dir is None:
        session_dir = Path(os.getenv("FV_SESSION_DIR", "."))
    session_dir = Path(session_dir)
    session_dir.mkdir(parents=True, exist_ok=True)

    # Snapshot directory from instance
    snapshot_dir = instance.script_output_dir

    # DB path in session dir
    db_path = session_dir / "map.duckdb"

    # Configure snapshot mod UDP port
    snapshot_udp_port = config.get_snapshot_port(instance.name)
    rcon.send_command(
        f"/c remote.call('snapshot', 'set_udp_port', {snapshot_udp_port})"
    )

    # Create database with schema
    database = SnapshotDatabase(db_path)
    database.ensure_schema()

    # Create snapshot loader (requires db connection and snapshot_dir)
    snapshot_loader = SnapshotLoader(database.connection, snapshot_dir)

    # Load initial data from snapshots
    load_result = snapshot_loader.load_all()

    return {
        "session_dir": session_dir,
        "snapshot_dir": snapshot_dir,
        "db_path": db_path,
        "database": database,
        "snapshot_loader": snapshot_loader,
        "snapshot_udp_port": snapshot_udp_port,
        "load_result": load_result,
    }


# For direct execution/testing
if __name__ == "__main__":
    from .rcon import load_rcon_scope
    from . import BoilerplateContext, Scope

    # Load RCON first
    ctx = BoilerplateContext(Scope.SNAPSHOT)
    ctx.update(load_rcon_scope())

    # Then snapshot
    ctx.update(load_snapshot_scope(ctx))

    print("✅ Snapshot scope loaded")
    print(f"   Snapshot dir: {ctx['snapshot_dir']}")
    print(f"   DB path: {ctx['db_path']}")

    # Test query - use database.connection for DuckDB queries
    result = (
        ctx["database"]
        .connection.execute("SELECT COUNT(*) as count FROM map_entity")
        .fetchone()
    )
    print(f"   Entity count: {result}")
