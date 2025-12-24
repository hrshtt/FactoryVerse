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
    
    def _generate_database_summary(self) -> str:
        """
        Generate a summary showing what data exists in the database with actual query results.
        
        Returns:
            Markdown formatted database summary with query → result pairs
        """
        summary_code = """
with playing_factorio():
    import json
    con = map_db.connection
    
    results = {}
    
    # 1. What resource types and patches exist on the map?
    try:
        resource_patches = con.execute('''
            SELECT resource_name, patch_id, total_amount, tile_count,
                   CAST(centroid AS STRUCT(x DOUBLE, y DOUBLE)).x as x,
                   CAST(centroid AS STRUCT(x DOUBLE, y DOUBLE)).y as y
            FROM resource_patch
            ORDER BY resource_name, patch_id
        ''').fetchall()
        results['resource_patches'] = [
            {'name': r[0], 'patch_id': r[1], 'amount': r[2], 
             'tiles': r[3], 'x': r[4], 'y': r[5]} 
            for r in resource_patches
        ]
    except:
        results['resource_patches'] = []
    
    # 2. What natural entities exist? (trees, rocks)
    try:
        entity_types = con.execute('''
            SELECT type, COUNT(*) as count
            FROM resource_entity
            GROUP BY type
            ORDER BY type
        ''').fetchall()
        results['entity_types'] = [
            {'type': r[0], 'count': r[1]} 
            for r in entity_types
        ]
    except:
        results['entity_types'] = []
    
    # 3. How much water is on the map?
    try:
        water_patches = con.execute('''
            SELECT patch_id, tile_count,
                   CAST(centroid AS STRUCT(x DOUBLE, y DOUBLE)).x as x,
                   CAST(centroid AS STRUCT(x DOUBLE, y DOUBLE)).y as y
            FROM water_patch
            ORDER BY patch_id
        ''').fetchall()
        results['water_patches'] = [
            {'patch_id': r[0], 'tiles': r[1], 'x': r[2], 'y': r[3]}
            for r in water_patches
        ]
        results['water'] = {
            'patches': len(water_patches),
            'tiles': sum(r[1] for r in water_patches) if water_patches else 0
        }
    except:
        results['water_patches'] = []
        results['water'] = {'patches': 0, 'tiles': 0}
    
    # 4. What entities have been placed?
    try:
        placed_entities = con.execute('''
            SELECT entity_name, COUNT(*) as count
            FROM map_entity
            GROUP BY entity_name
            ORDER BY entity_name
        ''').fetchall()
        results['placed_entities'] = [
            {'name': r[0], 'count': r[1]} 
            for r in placed_entities
        ]
    except:
        results['placed_entities'] = []
    
    print(json.dumps(results))
"""
        
        try:
            result = self.runtime.execute_code(summary_code, compress_output=False)
            data = json.loads(result)
            
            lines = []
            lines.append("## Database Summary\n\n")
            
            # Resource patches with coordinates
            if data.get('resource_patches'):
                lines.append("**Query:** What resource patches exist on the map?\n")
                lines.append("```sql\n")
                lines.append("SELECT resource_name, patch_id, total_amount, tile_count,\n")
                lines.append("       centroid.x as x, centroid.y as y\n")
                lines.append("FROM resource_patch\n")
                lines.append("ORDER BY resource_name, patch_id\n")
                lines.append("```\n\n")
                lines.append("**Result:**\n\n")
                lines.append("| Resource | Patch ID | Amount | Tiles | Coordinates |\n")
                lines.append("|----------|----------|--------|-------|-------------|\n")
                for r in data['resource_patches']:
                    amount_str = f"{r['amount']:,}" if r['amount'] >= 1000 else str(r['amount'])
                    lines.append(f"| {r['name']} | #{r['patch_id']} | {amount_str} | {r['tiles']} | ({r['x']:.0f}, {r['y']:.0f}) |\n")
                lines.append("\n")
            
            # Natural entities
            if data.get('entity_types'):
                lines.append("**Query:** What natural entities exist? (trees, rocks)\n")
                lines.append("```sql\n")
                lines.append("SELECT type, COUNT(*) as count\n")
                lines.append("FROM resource_entity\n")
                lines.append("GROUP BY type\n")
                lines.append("```\n\n")
                lines.append("**Result:**\n\n")
                lines.append("| Entity Type | Count |\n")
                lines.append("|-------------|-------|\n")
                for e in data['entity_types']:
                    lines.append(f"| {e['type']} | {e['count']:,} |\n")
                lines.append("\n")
            
            # Water patches with coordinates
            if data.get('water_patches'):
                lines.append("**Query:** What water patches exist on the map?\n")
                lines.append("```sql\n")
                lines.append("SELECT patch_id, tile_count, centroid.x as x, centroid.y as y\n")
                lines.append("FROM water_patch\n")
                lines.append("ORDER BY patch_id\n")
                lines.append("```\n\n")
                lines.append("**Result:**\n\n")
                lines.append("| Patch ID | Tiles | Coordinates |\n")
                lines.append("|----------|-------|-------------|\n")
                for w in data['water_patches']:
                    lines.append(f"| #{w['patch_id']} | {w['tiles']} | ({w['x']:.0f}, {w['y']:.0f}) |\n")
                lines.append("\n")
            
            # Placed entities
            if data.get('placed_entities'):
                lines.append("**Query:** What entities have been placed?\n")
                lines.append("```sql\n")
                lines.append("SELECT entity_name, COUNT(*) as count\n")
                lines.append("FROM map_entity\n")
                lines.append("GROUP BY entity_name\n")
                lines.append("```\n\n")
                lines.append("**Result:**\n\n")
                lines.append("| Entity | Count |\n")
                lines.append("|--------|-------|\n")
                for e in data['placed_entities']:
                    lines.append(f"| {e['name']} | {e['count']} |\n")
                lines.append("\n")
            
            return "".join(lines)
        
        except Exception as e:
            # Fallback if database summary fails
            return f"## Database Summary\n\n*Database summary unavailable: {e}*\n\n"
    
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
    
    # Get inventory - debug what we're actually getting
    inv_stacks = inventory.item_stacks
    inv_items = {}
    if inv_stacks:
        for stack in inv_stacks:
            inv_items[stack.name] = stack.count
    
    # Get technology and recipe information
    researched_techs = research.get_technologies(researched_only=True)
    researched_names = [t.name for t in researched_techs]
    
    # Get recipes - call without category to get all enabled recipes
    enabled_recipes_data = crafting.get_recipes(enabled_only=True)
    enabled_recipe_names = [r.name for r in enabled_recipes_data]
    
    # Query DuckDB for comprehensive map data
    con = map_db.connection
    
    # All resource patches (no sorting, just list them all)
    all_patches = con.execute('''
        SELECT 
            patch_id,
            resource_name,
            total_amount,
            tile_count,
            CAST(centroid AS STRUCT(x DOUBLE, y DOUBLE)).x as x,
            CAST(centroid AS STRUCT(x DOUBLE, y DOUBLE)).y as y
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
            f"*Generated at session start*\n\n",
        ]
        
        # Add categorical references at the beginning
        try:
            from FactoryVerse.llm.categorical_references import CategoricalReferenceGenerator
            
            cat_gen = CategoricalReferenceGenerator()
            categorical_refs = cat_gen.generate_combined_reference()
            summary_lines.append(categorical_refs)
            summary_lines.append("\n---\n\n")
        except Exception as e:
            # If categorical reference generation fails, continue without it
            summary_lines.append(f"*Categorical references unavailable: {e}*\n\n")
        
        # Add database summary with query→result pairs
        database_summary = self._generate_database_summary()
        summary_lines.append(database_summary)
        summary_lines.append("\n")
        
        # Add agent status
        summary_lines.append("## Agent Status\n")
        summary_lines.append(f"**Position:** ({state['position']['x']:.1f}, {state['position']['y']:.1f})\n")
        
        # Inventory section
        summary_lines.append("\n## Inventory\n")
        if state['inventory']:
            for item, count in sorted(state['inventory'].items()):
                summary_lines.append(f"- **{item}**: {count}\n")
        else:
            summary_lines.append("*Empty*\n")
        
        # Map overview
        if state['map_bounds'] and state['map_bounds']['max_x'] is not None:
            bounds = state['map_bounds']
            width = bounds['max_x'] - bounds['min_x']
            height = bounds['max_y'] - bounds['min_y']
            summary_lines.append("\n## Map Overview\n")
            summary_lines.append(f"**Explored area:** {width:.0f} × {height:.0f} tiles\n")
            summary_lines.append(f"**Bounds:** X=[{bounds['min_x']:.0f}, {bounds['max_x']:.0f}], Y=[{bounds['min_y']:.0f}, {bounds['max_y']:.0f}]\n")
        
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
