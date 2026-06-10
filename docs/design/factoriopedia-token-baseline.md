# Factoriopedia Token Baseline

> Measured before/after Factoriopedia implementation on branch `factoriopedia`

## Baseline (2026-01-23)

| Component | Tokens (cl100k_base) |
|-----------|----------------------|
| **Full System Prompt** | **21,173** |
| API Reference | 14,452 |
| Schema Reference | 3,992 |
| Entity Inspection Schema | 1,651 |
| Core Prompt | ~1,078 |

## Post-Implementation (2026-01-23)

| Component | Tokens | Change |
|-----------|--------|--------|
| **Full System Prompt** | **20,072** | **-1,101 (-5.2%)** |
| Entity Inspection Schema | 191 | -1,460 |
| Factoriopedia section | +359 | (new) |

## What Changed

### Moved to Factoriopedia

The detailed entity inspection schema (all capability slot fields) was moved to on-demand lookup:

**Before** (1,651 tokens): Listed every field of every capability state (BurnerState, CrafterState, MinerState, etc.) with types and descriptions.

**After** (191 tokens): Concept explanation + list of slot names + "use factoriopedia for details"

### Factoriopedia Now Shows

When you query an entity, factoriopedia now shows:
- Inspection slots available for that entity type
- Fields in each slot

```
$ factoriopedia burner-mining-drill

[Entity]
  Type: mining-drill
  Size: 2x2
  Power: 150kW (burner)
  Properties:
    - mining_speed: 0.25
    - mining_radius: 0.99
  Inspection slots (.inspect()):
    - burner: heat, remaining_burning_fuel, fuel_inventory, currently_burning
    - miner: mining_progress, mining_target
```

## Further Opportunities

Based on token analysis, additional savings are possible:

| Section | Current Tokens | Opportunity |
|---------|---------------|-------------|
| `placement_spatial` | 4,077 | Reduce to 1 example per method |
| `view_RemoteView` | 1,756 | Consolidate SQL examples |
| `core_types` | 1,488 | Trim type definitions |
| `view_ReachableView` | 1,426 | Reduce example verbosity |

Total potential: ~3,000-4,000 additional tokens if examples are aggressively trimmed.

## CLI Usage

```bash
# Look up any entity, recipe, item, or technology
uv run python -m FactoryVerse.game.factory.factoriopedia <name>

# Options
-v, --verbose        Show full "used in" lists
-t, --time           Time format: ticks, seconds, both
-l, --list           List: crafters, entities, recipes
```
