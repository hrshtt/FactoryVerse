"""RCON scope loader - Scope.RCON

This module provides the base RCON connection layer.
All other scopes build on top of this.

Components loaded:
    - config: FactoryVerseConfig
    - instance: FactorioInstance (client or server)
    - rcon: Connected RCONClient

Usage:
    >>> from FactoryVerse.infra.boilerplate.rcon import load_rcon_scope
    >>> ctx = load_rcon_scope(instance='client')
    >>> ctx['rcon'].send_command('/c print("hello")')
"""

import os
from typing import Optional, Dict, Any


def load_rcon_scope(instance: Optional[str] = None) -> Dict[str, Any]:
    """Load RCON scope components.

    Args:
        instance: Instance name ('client' or 'server_N'), auto-detect if None

    Returns:
        Dict with: config, instance, rcon
    """
    from FactoryVerse.config import get_config
    from FactoryVerse.infra.instance_manager import FactorioInstanceManager
    from FactoryVerse.utils.rcon_utils import create_rcon_client

    # Get global config
    config = get_config()

    # Detect or use specified instance
    if instance is not None:
        # Set env var for consistency with other code paths
        os.environ["FV_INSTANCE"] = instance

    factorio_instance = FactorioInstanceManager.from_env(config)

    # Create RCON connection
    rcon_client = create_rcon_client(
        factorio_instance.rcon_host,
        factorio_instance.rcon_port,
        factorio_instance.rcon_password,
        initialize=True,
    )

    return {
        "config": config,
        "instance": factorio_instance,
        "rcon": rcon_client,
    }


# For direct execution/testing
if __name__ == "__main__":
    ctx = load_rcon_scope()
    print(f"✅ Connected to {ctx['instance'].name}")
    print(f"   RCON: {ctx['instance'].rcon_host}:{ctx['instance'].rcon_port}")

    # Test command
    result = ctx["rcon"].send_command('/c rcon.print("RCON scope test")')
    print(f"   Response: {result}")
