"""Port configuration utilities for FactoryVerse servers.

Handles runtime configuration of UDP ports for snapshot and agent mods.
"""

import time
from typing import Optional
from factorio_rcon import RCONClient

from FactoryVerse.environment.config import FactoryVerseConfig, get_config
from FactoryVerse.game.snapshot import MapSnapshotInterface
from FactoryVerse.utils.rcon_utils import create_rcon_client


def configure_server_snapshot_port(
    server_id: int,
    config: Optional[FactoryVerseConfig] = None,
    max_retries: int = 10,
    retry_delay: float = 2.0,
) -> bool:
    """Configure snapshot UDP port for a server instance via RCON.
    
    Args:
        server_id: Server instance ID (0, 1, 2, ...)
        config: Optional FactoryVerseConfig (uses default if None)
        max_retries: Maximum number of connection attempts
        retry_delay: Delay between retries in seconds
        
    Returns:
        True if configuration succeeded, False otherwise
    """
    cfg = config or get_config()
    
    # Get the snapshot port for this server
    snapshot_port = cfg.get_snapshot_port(f"server_{server_id}")
    rcon_port = cfg.get_rcon_port(f"server_{server_id}")
    
    # Wait for server to be ready and configure
    for attempt in range(max_retries):
        try:
            rcon = create_rcon_client(
                host=cfg.rcon_host,
                port=rcon_port,
                password=cfg.rcon_password,
                initialize=True
            )

            # Use MapSnapshotInterface adapter
            map_api = MapSnapshotInterface(rcon)

            # Call the remote interface to set snapshot port
            map_api.set_udp_port(snapshot_port)

            # Verify it was set correctly
            verify_result = map_api.get_udp_port()

            if verify_result == snapshot_port:
                print(f"✅ Server {server_id}: Snapshot port configured to {snapshot_port}")
                return True
            else:
                print(f"⚠️  Server {server_id}: Port configuration verification failed (attempt {attempt + 1}/{max_retries})")
                
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"⏳ Server {server_id}: Waiting for RCON... (attempt {attempt + 1}/{max_retries})")
                time.sleep(retry_delay)
            else:
                print(f"❌ Server {server_id}: Failed to configure snapshot port: {e}")
                return False
    
    return False


def configure_all_server_snapshot_ports(
    num_servers: int,
    config: Optional[FactoryVerseConfig] = None,
) -> dict[int, bool]:
    """Configure snapshot UDP ports for all server instances.
    
    Args:
        num_servers: Number of server instances to configure
        config: Optional FactoryVerseConfig (uses default if None)
        
    Returns:
        Dict mapping server_id to success status
    """
    results = {}
    
    print(f"\n🔧 Configuring snapshot ports for {num_servers} server(s)...")
    
    for server_id in range(num_servers):
        results[server_id] = configure_server_snapshot_port(server_id, config)
    
    # Summary
    successful = sum(1 for success in results.values() if success)
    print(f"\n📊 Port configuration: {successful}/{num_servers} servers configured successfully")
    
    return results

