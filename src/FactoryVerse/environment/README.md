# FactoryVerse Environment Module

The **canonical orchestrator** for composing FactoryVerse's tiered runtime stack.

## Quick Start

```python
from FactoryVerse.environment import Environment, Tier

# Full agent run
async with Environment.for_agent(mode="autonomous") as env:
    await env.tier6.run_loop()

# Testing with minimal runtime
async with Environment.for_testing(scenario="test-ground") as env:
    result = env.tier3.execute_lua("return game.tick")
```

## Tiers

| Tier | Name | Description |
|------|------|-------------|
| 1 | Factorio Infra | Client/Server with mods |
| 2 | Settings | Scenario/save loading |
| 3 | Python Infra | RCON + UDP connections |
| 4 | Runtime | Agent modules (remote_view, etc.) |
| 5 | Specification | System prompt generation |
| 6 | Interaction | LLM orchestration |

See [ENVIRONMENT_DESIGN.md](../../docs/architecture/ENVIRONMENT_DESIGN.md) for full documentation.
