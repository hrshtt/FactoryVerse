"""Runtime scope loader - Scope.RUNTIME

This module creates the full AgentRuntime with all affordances.
Builds on AGENT scope.

Components loaded (in addition to AGENT):
    - runtime: Full AgentRuntime instance
    - Convenience accessors: walking, crafting, inventory, etc.

Usage:
    >>> from FactoryVerse.infra.llm.boilerplate import load, Scope
    >>> ctx = load(scope=Scope.RUNTIME)
    >>> await ctx.start()
    >>> await ctx['runtime'].walking.walk_to(MapPosition(10, 10))
"""

from typing import Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from . import BoilerplateContext


def load_runtime_scope(ctx: "BoilerplateContext") -> Dict[str, Any]:
    """Load runtime scope components.

    Requires AGENT scope to be loaded first.

    Args:
        ctx: BoilerplateContext with AGENT scope loaded

    Returns:
        Dict with: runtime, plus all convenience accessors
    """
    from FactoryVerse.runtime import create_runtime

    rcon = ctx["rcon"]
    agent_id = ctx["agent_id"]
    udp_port = ctx["udp_port"]
    snapshot_dir = ctx["snapshot_dir"]
    db_path = ctx["db_path"]

    # Create full runtime
    runtime = create_runtime(
        rcon_client=rcon,
        agent_id=agent_id,
        udp_port=udp_port,
        snapshot_dir=snapshot_dir,
        db_path=db_path,
    )

    # Return runtime and convenience accessors
    return {
        "runtime": runtime,
        # Convenience accessors (available after runtime.start())
        "walking": runtime.walking,
        "crafting": runtime.crafting,
        "research": runtime.research,
        "inventory": runtime.inventory,
        "reachable": runtime.reachable,
        "resources": runtime.resources,  # Alias for reachable
        "entity_ops": runtime.entity_ops,
        "placement": runtime.placement,
        "ghost_builder": runtime.ghost_builder,
        "placement_hints": runtime.placement_hints,
        "remote_view": runtime.remote_view,
    }


def get_runtime_script() -> str:
    """Get the runtime setup script for Jupyter execution.

    This returns Python code that can be executed in a Jupyter kernel
    to set up the full runtime with all variables in the namespace.

    Returns:
        Python code string
    """
    # Read the legacy boilerplate.py for backward compatibility
    from pathlib import Path

    legacy_path = Path(__file__).parent.parent / "boilerplate.py"
    if legacy_path.exists():
        return legacy_path.read_text()

    # Fallback: generate from this module
    return """
# Generated runtime setup
from FactoryVerse.infra.llm.boilerplate import load, Scope
from FactoryVerse.factory.types import MapPosition, Direction
from FactoryVerse.agent.placement_hints import ConnectionType

# Load full runtime
_ctx = load(scope=Scope.RUNTIME)

# Extract components into namespace
config = _ctx['config']
instance = _ctx['instance']
rcon_client = _ctx['rcon']
runtime = _ctx['runtime']

# Convenience accessors
walking = runtime.walking
crafting = runtime.crafting
research = runtime.research
inventory = runtime.inventory
reachable = runtime.reachable
resources = runtime.resources
entity_ops = runtime.entity_ops
placement = runtime.placement
ghost_builder = runtime.ghost_builder
placement_hints = runtime.placement_hints
remote_view = runtime.remote_view

# Start runtime (async)
await _ctx.start()

print(f"✅ Runtime loaded for {instance.name}")
print(f"   Agent: {_ctx['agent_id']} on UDP {_ctx['udp_port']}")
"""


# For direct execution/testing
if __name__ == "__main__":
    import asyncio
    from .rcon import load_rcon_scope
    from .snapshot import load_snapshot_scope
    from .agent import load_agent_scope
    from . import BoilerplateContext, Scope

    async def main():
        # Load all prerequisites
        ctx = BoilerplateContext(Scope.RUNTIME)
        ctx.update(load_rcon_scope())
        ctx.update(load_snapshot_scope(ctx))
        ctx.update(load_agent_scope(ctx))

        # Then runtime
        ctx.update(load_runtime_scope(ctx))

        print("✅ Runtime scope loaded")
        print(f"   Runtime: {ctx['runtime']}")
        print("   Affordances: walking, crafting, inventory, etc.")

        # Start runtime
        await ctx.start()
        print("   Runtime started!")

        # Cleanup
        await ctx.stop()
        print("   Runtime stopped")

    asyncio.run(main())
