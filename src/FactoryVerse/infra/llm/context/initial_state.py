"""Generate initial state summaries for agent sessions.

This module creates the initial state document that is injected as the first
user message to orient the agent about its current situation. The document
shows Python code that was executed and its output, establishing patterns
for how the agent should query and interact with the game.
"""

import json
from pathlib import Path
from typing import Any, Protocol


class RuntimeProtocol(Protocol):
    """Protocol for runtime objects that can execute code."""

    def execute_code(self, code: str, compress_output: bool = False) -> str:
        """Execute code and return output."""
        ...


class InitialStateGenerator:
    """Generate initial state summary for agent.

    The generated summary follows a "code + output" pattern to demonstrate
    how to query the game state using the available accessors.
    """

    def __init__(self, runtime: RuntimeProtocol):
        """
        Initialize generator.

        Args:
            runtime: Object with execute_code() method (FactoryVerseRuntime or adapter)
        """
        self.runtime = runtime

    def _execute_and_capture(self, code: str, description: str) -> tuple[str, str]:
        """Execute code and return the code + output as formatted markdown.

        Args:
            code: Python code to execute
            description: Human-readable description of what the code does

        Returns:
            Tuple of (formatted_markdown, raw_output)
        """
        try:
            output = self.runtime.execute_code(code, compress_output=False)
        except Exception as e:
            output = f"Error: {e}"

        # Clean up code for display (remove leading/trailing whitespace per line)
        display_code = "\n".join(line for line in code.strip().split("\n"))

        markdown = f"""### {description}

**Code executed:**
```python
{display_code}
```

**Output:**
```
{output}
```
"""
        return markdown, output

    def _generate_position_and_inventory(self) -> tuple[str, dict[str, Any]]:
        """Generate agent position and inventory section.

        Returns:
            Tuple of (markdown, parsed_data)
        """
        code = """import json
pos = walking.current_position
inv_stacks = inventory.item_stacks
inv_dict = {s.name: s.count for s in inv_stacks} if inv_stacks else {}
print(json.dumps({
    "position": {"x": pos.x, "y": pos.y},
    "inventory": inv_dict
}))"""

        markdown, output = self._execute_and_capture(code, "Agent Position & Inventory")

        try:
            data = json.loads(output)
        except (json.JSONDecodeError, ValueError):
            data = {"position": {"x": 0, "y": 0}, "inventory": {}}

        return markdown, data

    def _generate_map_bounds(self) -> tuple[str, dict[str, Any]]:
        """Generate the agent's working-area bounds section (PROMPT-3).

        Without this the agent has no way to know its cell limits and
        probes them with blind walks (field run: x=-5, y=-100, (200,70)).

        Returns:
            Tuple of (markdown, parsed_data); empty markdown if no
            cell-based scenario adapter is available.
        """
        code = """import json
pos = walking.current_position
cfg = scenario.config
cell_x = int(pos.x // cfg.cell_size)
cell_y = int(pos.y // cfg.cell_size)
cell_index = cell_y * cfg.grid_size + cell_x
b = scenario.get_cell_bounds(cell_index)
print(json.dumps({
    "cell_index": cell_index,
    "buildable_area": {
        "left_top": {"x": b.left_top.x, "y": b.left_top.y},
        "right_bottom": {"x": b.right_bottom.x, "y": b.right_bottom.y},
    },
}))"""

        markdown, output = self._execute_and_capture(
            code, "Your Working Area (IMPORTANT: hard bounds)"
        )

        try:
            data = json.loads(output)
        except (json.JSONDecodeError, ValueError):
            return "", {}

        area = data.get("buildable_area", {})
        lt, rb = area.get("left_top", {}), area.get("right_bottom", {})
        markdown += (
            f"\n**You are confined to cell {data.get('cell_index')}: "
            f"({lt.get('x')}, {lt.get('y')}) to ({rb.get('x')}, {rb.get('y')}).** "
            "Tiles outside these bounds are out-of-map: unwalkable, unbuildable, "
            "and contain nothing. Do not spend actions probing beyond them.\n"
        )
        return markdown, data

    def _generate_resource_aggregates(self) -> tuple[str, list[dict]]:
        """Generate resource aggregates from resource tiles.

        Returns:
            Tuple of (markdown, parsed_data)
        """
        code = '''import json

# Query resource aggregates from resource_tile table
result = remote_view.query("""
    SELECT 
        name as resource_name,
        COUNT(*) as tile_count,
        SUM(amount) as total_amount,
        AVG(position_x) as avg_x,
        AVG(position_y) as avg_y
    FROM resource_tile
    GROUP BY name
    ORDER BY total_amount DESC
""")

aggregates = []
for r in result:
    aggregates.append({
        "resource": r["resource_name"],
        "tiles": r["tile_count"],
        "total_ore": r["total_amount"],
        "centroid": {"x": round(r["avg_x"], 1), "y": round(r["avg_y"], 1)}
    })
print(json.dumps(aggregates))'''

        markdown, output = self._execute_and_capture(
            code, "Resource Overview (Aggregated)"
        )

        try:
            data = json.loads(output)
        except (json.JSONDecodeError, ValueError):
            data = []

        return markdown, data

    def _generate_resource_locations(self) -> tuple[str, list[dict]]:
        """Generate top resource locations with positions.

        Returns:
            Tuple of (markdown, parsed_data)
        """
        code = '''import json

# Query top resource tiles by amount
result = remote_view.query("""
    SELECT 
        name as resource_name,
        position_x,
        position_y,
        amount
    FROM resource_tile
    ORDER BY amount DESC
    LIMIT 30
""")

resources = []
for r in result:
    resources.append({
        "resource": r["resource_name"],
        "amount": r["amount"],
        "position": {"x": round(r["position_x"], 1), "y": round(r["position_y"], 1)}
    })
print(json.dumps(resources))'''

        markdown, output = self._execute_and_capture(code, "Top Resource Locations")

        try:
            data = json.loads(output)
        except (json.JSONDecodeError, ValueError):
            data = []

        return markdown, data

    def _generate_placed_entities(self) -> tuple[str, list[dict]]:
        """Generate summary of placed entities.

        Returns:
            Tuple of (markdown, parsed_data)
        """
        code = '''import json

# Query placed entities using remote_view
result = remote_view.query("""
    SELECT entity_name, COUNT(*) as count
    FROM map_entity
    GROUP BY entity_name
    ORDER BY count DESC
""")

entities = [{"name": r["entity_name"], "count": r["count"]} for r in result]
print(json.dumps(entities))'''

        markdown, output = self._execute_and_capture(code, "Placed Entities on Map")

        try:
            data = json.loads(output)
        except (json.JSONDecodeError, ValueError):
            data = []

        return markdown, data

    def _generate_water_patches(self) -> tuple[str, list[dict]]:
        """Generate water tile summary.

        Returns:
            Tuple of (markdown, parsed_data)
        """
        code = '''import json

# Query water tiles using remote_view
result = remote_view.query("""
    SELECT 
        COUNT(*) as tile_count,
        AVG(position_x) as avg_x,
        AVG(position_y) as avg_y,
        MIN(position_x) as min_x,
        MAX(position_x) as max_x,
        MIN(position_y) as min_y,
        MAX(position_y) as max_y
    FROM water_tile
""")

if result and result[0]["tile_count"] > 0:
    r = result[0]
    water = [{
        "tiles": r["tile_count"],
        "centroid": {"x": round(r["avg_x"], 1), "y": round(r["avg_y"], 1)},
        "bounds": {
            "min": {"x": round(r["min_x"], 1), "y": round(r["min_y"], 1)},
            "max": {"x": round(r["max_x"], 1), "y": round(r["max_y"], 1)}
        }
    }]
else:
    water = []
print(json.dumps(water))'''

        markdown, output = self._execute_and_capture(
            code, "Water Areas (for offshore pumps)"
        )

        try:
            data = json.loads(output)
        except (json.JSONDecodeError, ValueError):
            data = []

        return markdown, data

    def _generate_natural_entities(self) -> tuple[str, dict[str, int]]:
        """Generate natural entity counts (trees, rocks).

        Returns:
            Tuple of (markdown, parsed_data)
        """
        code = '''import json

# Query natural entities using remote_view
result = remote_view.query("""
    SELECT entity_type, COUNT(*) as count
    FROM resource_entity
    GROUP BY entity_type
""")

entities = {r["entity_type"]: r["count"] for r in result}
print(json.dumps(entities))'''

        markdown, output = self._execute_and_capture(
            code, "Natural Entities (trees, rocks)"
        )

        try:
            data = json.loads(output)
        except (json.JSONDecodeError, ValueError):
            data = {}

        return markdown, data

    def _generate_tech_and_recipes(
        self, researched: list[str], enabled: list[str]
    ) -> str:
        """Generate technology and recipe section.

        Args:
            researched: List of researched technology names
            enabled: List of enabled recipe names

        Returns:
            Markdown formatted section
        """
        try:
            from FactoryVerse.infra.llm.prompts.tech_recipes import (
                TechRecipePromptGenerator,
            )

            tech_recipe_gen = TechRecipePromptGenerator()
            return tech_recipe_gen.generate_combined_prompt(
                researched=researched,
                enabled_recipes=enabled,
                tech_limit=8,
                recipe_limit=12,
            )
        except Exception as e:
            return f"*Tech/recipe information unavailable: {e}*\n"

    def generate_summary(self, session_dir: Path) -> str:
        """
        Generate markdown summary of current game state.

        The summary shows Python code that was executed and its output,
        demonstrating how to query the game state using the available accessors.

        Args:
            session_dir: Session directory to save summary to

        Returns:
            Markdown summary text
        """
        lines = [
            "# Initial Game State\n\n",
            "This document shows the Python code that was executed to understand ",
            "your current situation. You can use similar patterns to query the game state.\n\n",
        ]

        # Add categorical references at the beginning (if available)
        try:
            from FactoryVerse.infra.llm.prompts.categorical import (
                CategoricalReferenceGenerator,
            )

            cat_gen = CategoricalReferenceGenerator()
            categorical_refs = cat_gen.generate_combined_reference()
            lines.append(categorical_refs)
            lines.append("\n---\n\n")
        except Exception:
            pass  # Skip if unavailable

        lines.append("## Code Execution Results\n\n")
        lines.append("The following code was executed at session start:\n\n")

        # Position and Inventory
        pos_md, pos_data = self._generate_position_and_inventory()
        lines.append(pos_md)
        lines.append("\n")

        # Working-area bounds (PROMPT-3): only emitted when a cell-based
        # scenario adapter answers; harmless no-op otherwise
        bounds_md, bounds_data = self._generate_map_bounds()
        if bounds_data:
            lines.append(bounds_md)
            lines.append("\n")

        # Resource Aggregates
        agg_md, _ = self._generate_resource_aggregates()
        lines.append(agg_md)
        lines.append("\n")

        # Top Resource Locations
        resources_md, resources_data = self._generate_resource_locations()
        lines.append(resources_md)
        lines.append("\n")

        # Placed Entities
        entities_md, entities_data = self._generate_placed_entities()
        if entities_data:  # Only show if entities exist
            lines.append(entities_md)
            lines.append("\n")

        # Water Patches
        water_md, water_data = self._generate_water_patches()
        if water_data:  # Only show if water exists
            lines.append(water_md)
            lines.append("\n")

        # Natural Entities
        natural_md, natural_data = self._generate_natural_entities()
        if natural_data:  # Only show if natural entities exist
            lines.append(natural_md)
            lines.append("\n")

        # Technology & Recipes section
        lines.append("---\n\n")

        # Get tech/recipe data via RCON
        # Access rcon_client and agent_id from boilerplate's global namespace
        tech_recipe_code = """import json

# Initialize defaults
enabled_recipe_names = []
researched_tech_names = []

# Access rcon_client and agent_id from boilerplate globals
# These are set up in boilerplate.py and available in the notebook namespace
try:
    # Get enabled recipes via agent interface
    recipes_cmd = f"/c rcon.print(helpers.table_to_json(remote.call('{agent_id}', 'get_recipes')))"
    recipes_result = rcon_client.send_command(recipes_cmd)
    
    if recipes_result:
        recipes = json.loads(recipes_result)
        # Extract recipe names from the result
        if isinstance(recipes, list):
            for r in recipes:
                if isinstance(r, dict) and r.get("name"):
                    enabled_recipe_names.append(r["name"])
except Exception as e:
    print(f"Error getting recipes: {e}")

try:
    # Get researched technologies
    techs_cmd = f"/c rcon.print(helpers.table_to_json(remote.call('{agent_id}', 'get_technologies')))"
    techs_result = rcon_client.send_command(techs_cmd)
    
    if techs_result:
        techs = json.loads(techs_result)
        # Extract researched tech names
        if isinstance(techs, dict):
            for tech_name, tech_data in techs.items():
                if isinstance(tech_data, dict) and tech_data.get("researched", False):
                    researched_tech_names.append(tech_name)
        elif isinstance(techs, list):
            # Handle list format (actual return type)
            for tech in techs:
                if isinstance(tech, dict) and tech.get("researched", False):
                    researched_tech_names.append(tech.get("name", ""))
except Exception as e:
    print(f"Error getting technologies: {e}")

print(json.dumps({
    "enabled_recipes": enabled_recipe_names,
    "researched_technologies": researched_tech_names
}))"""

        try:
            output = self.runtime.execute_code(tech_recipe_code, compress_output=False)
            # Parse the JSON output
            try:
                data = json.loads(output)
                enabled = data.get("enabled_recipes", [])
                researched = data.get("researched_technologies", [])
            except (json.JSONDecodeError, ValueError):
                # Fallback: try to extract from output
                enabled = []
                researched = []
        except Exception:
            enabled = []
            researched = []

        tech_section = self._generate_tech_and_recipes(researched, enabled)
        lines.append(tech_section)
        lines.append("\n")

        # Quick reference summary
        lines.append("---\n\n")
        lines.append("## Quick Reference\n\n")

        # Position
        pos = pos_data.get("position", {"x": 0, "y": 0})
        lines.append(f"**Your position:** ({pos['x']:.1f}, {pos['y']:.1f})\n\n")

        # Inventory summary
        inv = pos_data.get("inventory", {})
        if inv:
            lines.append("**Inventory:**\n")
            for item, count in sorted(inv.items()):
                lines.append(f"- {item}: {count}\n")
        else:
            lines.append("**Inventory:** *Empty*\n")
        lines.append("\n")

        # Combine and save
        summary_text = "".join(lines)
        summary_path = session_dir / "initial_state.md"
        with open(summary_path, "w") as f:
            f.write(summary_text)

        return summary_text
