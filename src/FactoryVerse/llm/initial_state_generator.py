"""Generate initial state summaries for agent sessions."""
import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from FactoryVerse.agent_runtime import FactoryVerseRuntime


class InitialStateGenerator:
    """Generate initial state summary for agent."""
    
    def __init__(self, runtime: 'FactoryVerseRuntime'):
        """
        Initialize generator.
        
        Args:
            runtime: FactoryVerse runtime instance
        """
        self.runtime = runtime
    
    def generate_summary(self, session_dir: Path) -> str:
        """
        Generate markdown summary of current game state.
        
        Args:
            session_dir: Session directory to save summary to
            
        Returns:
            Markdown summary text
        """
        # Execute code to gather state information
        state_code = """
with playing_factorio():
    import json
    
    # Agent position
    pos = reachable.get_current_position()
    
    # Inventory
    inv_items = {}
    common_items = [
        'iron-plate', 'copper-plate', 'coal', 'stone',
        'iron-ore', 'copper-ore', 'stone-furnace',
        'burner-mining-drill', 'transport-belt'
    ]
    for item_name in common_items:
        count = inventory.get_total(item_name)
        if count > 0:
            inv_items[item_name] = count
    
    # Nearby resources (within reach)
    resources = []
    for resource_type in ['iron-ore', 'copper-ore', 'coal', 'stone']:
        try:
            patches = reachable.get_resource(resource_type)
            if patches:
                resources.append({
                    'type': resource_type,
                    'count': len(patches),
                    'positions': [{'x': p.position.x, 'y': p.position.y} for p in patches[:3]]
                })
        except:
            pass  # Resource not in reach
    
    # Nearby entities
    entities = reachable.get_entities()
    entity_counts = {}
    for entity in entities:
        entity_counts[entity.name] = entity_counts.get(entity.name, 0) + 1
    
    print(json.dumps({
        'position': {'x': pos.x, 'y': pos.y},
        'inventory': inv_items,
        'resources': resources,
        'entities': entity_counts
    }))
"""
        
        try:
            result = self.runtime.execute_code(state_code, compress_output=False)
            state = json.loads(result)
        except Exception as e:
            # Fallback if state gathering fails
            state = {
                'position': {'x': 0, 'y': 0},
                'inventory': {},
                'resources': [],
                'entities': {}
            }
        
        # Build markdown summary
        summary_lines = [
            "# Initial Game State\n",
            f"*Generated at session start*\n",
            "\n## Agent Status\n",
            f"**Position:** ({state['position']['x']:.1f}, {state['position']['y']:.1f})\n",
        ]
        
        # Inventory section
        summary_lines.append("\n## Inventory\n")
        if state['inventory']:
            for item, count in sorted(state['inventory'].items()):
                summary_lines.append(f"- **{item}**: {count}\n")
        else:
            summary_lines.append("*Empty*\n")
        
        # Resources section
        summary_lines.append("\n## Nearby Resources\n")
        if state['resources']:
            for resource in state['resources']:
                summary_lines.append(f"### {resource['type']}\n")
                summary_lines.append(f"- **Patches in reach:** {resource['count']}\n")
                if resource['positions']:
                    summary_lines.append("- **Sample positions:**\n")
                    for pos in resource['positions']:
                        summary_lines.append(f"  - ({pos['x']:.1f}, {pos['y']:.1f})\n")
        else:
            summary_lines.append("*No resources in immediate reach*\n")
        
        # Entities section
        summary_lines.append("\n## Nearby Entities\n")
        if state['entities']:
            for entity_name, count in sorted(state['entities'].items()):
                summary_lines.append(f"- **{entity_name}**: {count}\n")
        else:
            summary_lines.append("*No entities nearby*\n")
        
        # Add guidance
        summary_lines.append("\n## Next Steps\n")
        summary_lines.append("Use the DSL to explore, gather resources, and build automation!\n")
        
        # Combine and save
        summary_text = "".join(summary_lines)
        summary_path = session_dir / "initial_state.md"
        with open(summary_path, 'w') as f:
            f.write(summary_text)
        
        return summary_text
