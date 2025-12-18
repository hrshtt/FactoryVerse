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
        Generate markdown summary of current game state using DuckDB queries.
        
        Args:
            session_dir: Session directory to save summary to
            
        Returns:
            Markdown summary text
        """
        # Execute code to gather comprehensive state from DuckDB AND tech/recipe info
        state_code = """
with playing_factorio():
    import json
    
    # Get agent position
    pos = reachable.get_current_position()
    
    # Get inventory
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
    
    # Get technology and recipe information
    researched_techs = research.get_technologies(researched_only=True)
    researched_names = [t['name'] for t in researched_techs]
    
    enabled_recipes_data = crafting.get_recipes(enabled_only=True)
    enabled_recipe_names = [r['name'] for r in enabled_recipes_data]
    
    # Query DuckDB for comprehensive map data
    con = map_db.connection
    
    # All resource patches (no sorting, just list them all)
    all_patches = con.execute('''
        SELECT 
            patch_id,
            resource_name,
            total_amount,
            tile_count,
            centroid.x as x,
            centroid.y as y
        FROM resource_patch
        ORDER BY resource_name, patch_id
    ''').fetchall()
    
    # Resource summary by type
    resource_summary = con.execute('''
        SELECT 
            resource_name,
            COUNT(*) as patch_count,
            SUM(total_amount) as total_amount,
            SUM(tile_count) as total_tiles
        FROM resource_patch
        GROUP BY resource_name
        ORDER BY resource_name
    ''').fetchall()
    
    # Water patches summary
    water_summary = con.execute('''
        SELECT 
            COUNT(*) as patch_count,
            SUM(tile_count) as total_tiles
        FROM water_patch
    ''').fetchone()
    
    # Map bounds
    map_bounds = con.execute('''
        SELECT 
            MIN(position.x) as min_x,
            MAX(position.x) as max_x,
            MIN(position.y) as min_y,
            MAX(position.y) as max_y
        FROM resource_tile
    ''').fetchone()
    
    # Trees and rocks count
    entities_count = con.execute('''
        SELECT 
            type,
            COUNT(*) as count
        FROM resource_entity
        GROUP BY type
    ''').fetchall()
    
    print(json.dumps({
        'position': {'x': pos.x, 'y': pos.y},
        'inventory': inv_items,
        'researched_techs': researched_names,
        'enabled_recipes': enabled_recipe_names,
        'all_patches': [
            {
                'patch_id': r[0],
                'name': r[1],
                'amount': r[2],
                'tiles': r[3],
                'x': r[4],
                'y': r[5]
            } for r in all_patches
        ],
        'resource_summary': [
            {
                'name': r[0],
                'patches': r[1],
                'total_amount': r[2],
                'total_tiles': r[3]
            } for r in resource_summary
        ],
        'water': {
            'patches': water_summary[0] if water_summary else 0,
            'tiles': water_summary[1] if water_summary else 0
        },
        'map_bounds': {
            'min_x': map_bounds[0] if map_bounds else 0,
            'max_x': map_bounds[1] if map_bounds else 0,
            'min_y': map_bounds[2] if map_bounds else 0,
            'max_y': map_bounds[3] if map_bounds else 0
        } if map_bounds else None,
        'entities': {r[0]: r[1] for r in entities_count}
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
                'researched_techs': [],
                'enabled_recipes': [],
                'all_patches': [],
                'resource_summary': [],
                'water': {'patches': 0, 'tiles': 0},
                'map_bounds': None,
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
        
        # Map overview
        if state['map_bounds']:
            bounds = state['map_bounds']
            width = bounds['max_x'] - bounds['min_x']
            height = bounds['max_y'] - bounds['min_y']
            summary_lines.append("\n## Map Overview\n")
            summary_lines.append(f"**Explored area:** {width:.0f} × {height:.0f} tiles\n")
            summary_lines.append(f"**Bounds:** X=[{bounds['min_x']:.0f}, {bounds['max_x']:.0f}], Y=[{bounds['min_y']:.0f}, {bounds['max_y']:.0f}]\n")
        
        # Resource summary
        summary_lines.append("\n## Resource Summary\n")
        if state['resource_summary']:
            for resource in state['resource_summary']:
                amount_str = f"{resource['amount']:,}" if resource['amount'] >= 1000 else str(resource['amount'])
                summary_lines.append(
                    f"- **{resource['name'].replace('-', ' ').title()}**: "
                    f"{resource['patches']} patches, "
                    f"{amount_str} total, "
                    f"{resource['tiles']} tiles\n"
                )
        else:
            summary_lines.append("*No resources found*\n")
        
        # All resource patches (verbose listing)
        summary_lines.append("\n## All Resource Patches\n")
        if state['all_patches']:
            # Group by resource type
            by_type = {}
            for patch in state['all_patches']:
                resource_name = patch['name']
                if resource_name not in by_type:
                    by_type[resource_name] = []
                by_type[resource_name].append(patch)
            
            for resource_name in sorted(by_type.keys()):
                patches = by_type[resource_name]
                summary_lines.append(f"### {resource_name.replace('-', ' ').title()}\n")
                for patch in patches:
                    amount_str = f"{patch['amount']:,}" if patch['amount'] >= 1000 else str(patch['amount'])
                    summary_lines.append(
                        f"- **Patch #{patch['patch_id']}**: "
                        f"{amount_str} @ ({patch['x']:.0f}, {patch['y']:.0f}), "
                        f"{patch['tiles']} tiles\n"
                    )
        else:
            summary_lines.append("*No resource patches in database*\n")
        
        # Water
        if state['water']['patches'] > 0:
            summary_lines.append("\n## Water\n")
            summary_lines.append(f"- **Patches:** {state['water']['patches']}\n")
            summary_lines.append(f"- **Total tiles:** {state['water']['tiles']:,}\n")
        
        # Natural entities (trees and rocks)
        if state['entities']:
            summary_lines.append("\n## Natural Entities\n")
            for entity_type, count in sorted(state['entities'].items()):
                summary_lines.append(f"- **{entity_type.title()}:** {count:,}\n")
        
        # Technology & Recipes section
        try:
            from FactoryVerse.llm.tech_recipe_prompt import TechRecipePromptGenerator
            
            tech_recipe_gen = TechRecipePromptGenerator()
            tech_recipe_section = tech_recipe_gen.generate_combined_prompt(
                researched=state.get('researched_techs', []),
                enabled_recipes=state.get('enabled_recipes', []),
                tech_limit=8,  # Show top 8 available technologies
                recipe_limit=12  # Show top 12 enabled recipes
            )
            summary_lines.append("\n")
            summary_lines.append(tech_recipe_section)
            summary_lines.append("\n")
        except Exception as e:
            # If tech/recipe generation fails, continue without it
            summary_lines.append("\n## Technology & Recipes\n")
            summary_lines.append(f"*Tech/recipe information unavailable: {e}*\n")
        
        # Add guidance
        summary_lines.append("\n## Next Steps\n")
        summary_lines.append("Use the DSL to explore, gather resources, and build automation!\n")
        summary_lines.append("Query the database for spatial analysis and planning.\n")
        summary_lines.append("Use `research.enqueue('tech-name')` to start researching technologies.\n")
        
        # Combine and save
        summary_text = "".join(summary_lines)
        summary_path = session_dir / "initial_state.md"
        with open(summary_path, 'w') as f:
            f.write(summary_text)
        
        return summary_text
