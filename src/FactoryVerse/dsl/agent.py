"""Agent class - main interface for interacting with Factorio."""

from typing import Dict, List, Optional, Any, Type
import asyncio

from FactoryVerse.infra.rcon_helper import RconHelper
from FactoryVerse.observations import MapView
from FactoryVerse.dsl.entities import (
    Entity,
    Machine,
    Assembler,
    ChemicalPlant,
    Furnace,
    MiningDrill,
    OffShorePump,
    Belt,
    Pipe,
    Resource,
    Ore,
    CrudeOil,
    Tree,
    SimpleEntity,
)
from FactoryVerse.dsl.items import ItemStack, Ingredient, ingredient_factory
from FactoryVerse.dsl.recipe import Recipe
from FactoryVerse.dsl.mixins import InventoryMixin, PlaceableMixin, RecipeMixin


class Agent:
    """Main agent interface - queries DuckDB directly."""
    
    def __init__(self, agent_id: int, helper: RconHelper, map_view: MapView):
        """
        Initialize agent.
        
        Args:
            agent_id: Agent ID
            helper: RconHelper instance
            map_view: MapView instance for queries
        """
        self.agent_id = agent_id
        self._helper = helper
        self._map_view = map_view
        self._force_recipes = None  # Cached recipes
        self._force_technologies = None  # Cached technologies
        self._entity_cache = {}  # Cache for entity objects
    
    def query_map(self, sql: str, params: Optional[List[Any]] = None) -> List[Dict[str, Any]]:
        """
        Query DuckDB directly - no abstraction.
        
        Args:
            sql: SQL query string
            params: Optional query parameters
        
        Returns:
            List of result dictionaries
        """
        return self._map_view.query(sql, params)
    
    @property
    def recipes(self) -> Dict[str, Recipe]:
        """
        Access to force-specific recipes.
        
        Note: This queries the agent's force recipes via RCON.
        Recipes are cached after first access.
        """
        if self._force_recipes is None:
            # Query agent's force recipes via RCON
            # We need to get the agent's force and then list recipes
            # For now, we'll use a helper RCON command to get recipes
            # This may need to be implemented in the Lua side
            try:
                # Use RCON command to get recipes from agent's force
                import json
                cmd = f"/c local agent = storage.agents[{self.agent_id}] if agent and agent.valid then local force = agent.force local recipes = {{}} for name, recipe in pairs(force.recipes) do if recipe.enabled then table.insert(recipes, name) end end rcon.print(helpers.table_to_json(recipes)) else rcon.print('[]') end"
                result_str = self._helper.rcon_client.send_command(cmd)
                recipe_names = json.loads(result_str)
                
                self._force_recipes = {
                    name: Recipe(name, self)
                    for name in recipe_names
                }
            except Exception:
                # Fallback: return empty dict if query fails
                self._force_recipes = {}
        return self._force_recipes
    
    @property
    def technologies(self) -> List[str]:
        """
        Access to force-specific technologies.
        
        Note: This queries the agent's force technologies via RCON.
        Technologies are cached after first access.
        """
        if self._force_technologies is None:
            # Query agent's force technologies via RCON
            try:
                # Use RCON command to get technologies from agent's force
                import json
                cmd = f"/c local agent = storage.agents[{self.agent_id}] if agent and agent.valid then local force = agent.force local techs = {{}} for name, tech in pairs(force.technologies) do if tech.enabled then table.insert(techs, name) end end rcon.print(helpers.table_to_json(techs)) else rcon.print('[]') end"
                result_str = self._helper.rcon_client.send_command(cmd)
                tech_names = json.loads(result_str)
                
                self._force_technologies = tech_names
            except Exception:
                # Fallback: return empty list if query fails
                self._force_technologies = []
        return self._force_technologies
    
    def get_item(self, item_name: str, count: int = 1) -> ItemStack:
        """
        Get item from agent inventory (or create ItemStack).
        
        Args:
            item_name: Item name
            count: Item count
        
        Returns:
            ItemStack object
        """
        ingredient = ingredient_factory(item_name)
        return ItemStack(ingredient, count)
    
    async def place(self, entity_name: str, position: Dict[str, float]) -> Entity:
        """
        Place an entity.
        
        Args:
            entity_name: Entity prototype name
            position: Position dict with 'x' and 'y' keys
        
        Returns:
            Entity object created from result
        """
        result = await self._helper.run_async(
            "action",
            "agent_place_entity",
            {
                "agent_id": self.agent_id,
                "entity_name": entity_name,
                "position": position,
            }
        )
        # Return Entity object created from result
        return self._entity_from_result(result, position)
    
    async def pickup(self, entity: Entity):
        """
        Pick up an entity.
        
        Args:
            entity: Entity to pick up
        
        Returns:
            Result from pickup action
        """
        return await self._helper.run_async(
            "action",
            "entity_pickup",
            {
                "agent_id": self.agent_id,
                "position_x": entity.position['x'],
                "position_y": entity.position['y'],
                "entity_name": entity.name,
            }
        )
    
    async def walk_to(self, position: Dict[str, float]):
        """Walk to position (async)."""
        return await self._helper.run_async(
            "action",
            "agent_walk_to",
            {
                "agent_id": self.agent_id,
                "position": position,
            }
        )
    
    async def teleport(self, position: Dict[str, float], fallback_to_safe: bool = True):
        """Teleport to position (sync)."""
        return await self._helper.run_async(
            "action",
            "agent_teleport",
            {
                "agent_id": self.agent_id,
                "position": position,
                "fallback_to_safe_position": fallback_to_safe,
            }
        )
    
    async def crafting_enqueue(self, recipe: str, count: int = 1):
        """Queue crafting (async)."""
        return await self._helper.run_async(
            "action",
            "agent_crafting_enqueue",
            {
                "agent_id": self.agent_id,
                "recipe": recipe,
                "count": count,
            }
        )
    
    async def mine_resource(self, resource_name: str, max_count: Optional[int] = None):
        """Mine resource (async)."""
        params = {
            "agent_id": self.agent_id,
            "resource_name": resource_name,
        }
        if max_count is not None:
            params["max_count"] = max_count
        return await self._helper.run_async("action", "mine_resource", params)
    
    def research_enqueue(self, technology: str):
        """Queue research (sync)."""
        return self._helper.run(
            "action",
            "research",
            {
                "agent_id": self.agent_id,
                "technology": technology,
            }
        )
    
    def _entity_from_result(
        self,
        result: Dict[str, Any],
        position: Optional[Dict[str, float]] = None
    ) -> Entity:
        """
        Create Entity object from query result or action result.
        
        Args:
            result: Result dictionary from query or action
            position: Optional position override
        
        Returns:
            Entity object of appropriate type
        """
        # Factory method to create right entity type
        name = result.get('name') or result.get('entity_name')
        entity_type = result.get('type') or result.get('entity_type')
        pos = position or {
            'x': result.get('position_x') or result.get('x'),
            'y': result.get('position_y') or result.get('y')
        }
        
        entity_class = self._get_entity_class(name, entity_type)
        entity = entity_class(
            position=pos,
            name=name,
            entity_type=entity_type,
            unit_number=result.get('unit_number'),
            map_view=self._map_view,
            helper=self._helper,
            agent_id=self.agent_id
        )
        
        # Apply mixins based on entity type
        self._apply_mixins(entity, entity_type)
        
        return entity
    
    def _get_entity_class(self, name: str, entity_type: str) -> Type[Entity]:
        """
        Factory method to get entity class.
        
        Args:
            name: Entity name
            entity_type: Entity type
        
        Returns:
            Entity class
        """
        # Map entity names/types to classes
        if entity_type == "assembling-machine":
            return Assembler
        elif entity_type == "chemical-plant":
            return ChemicalPlant
        elif entity_type == "furnace":
            return Furnace
        elif entity_type == "mining-drill":
            return MiningDrill
        elif entity_type == "offshore-pump":
            return OffShorePump
        elif entity_type in ("transport-belt", "underground-belt", "splitter"):
            return Belt
        elif entity_type in ("pipe", "pipe-to-ground"):
            return Pipe
        elif entity_type == "resource":
            if name in ("iron-ore", "copper-ore", "stone", "coal"):
                return Ore
            elif name == "crude-oil":
                return CrudeOil
            elif "tree" in name:
                return Tree
            else:
                return SimpleEntity
        return Entity
    
    def _apply_mixins(self, entity: Entity, entity_type: str):
        """
        Apply mixins to entity based on type.
        
        Args:
            entity: Entity instance
            entity_type: Entity type
        """
        # Apply InventoryMixin to entities with inventories
        if entity_type in (
            "assembling-machine", "furnace", "chemical-plant",
            "mining-drill", "chest", "inserter"
        ):
            # Dynamically add mixin methods
            for method_name in dir(InventoryMixin):
                if not method_name.startswith('_'):
                    method = getattr(InventoryMixin, method_name)
                    if callable(method):
                        setattr(entity, method_name, method.__get__(entity, type(entity)))
        
        # Apply RecipeMixin to entities that can have recipes
        if entity_type in ("assembling-machine", "furnace", "chemical-plant", "rocket-silo"):
            for method_name in dir(RecipeMixin):
                if not method_name.startswith('_'):
                    method = getattr(RecipeMixin, method_name)
                    if callable(method):
                        setattr(entity, method_name, method.__get__(entity, type(entity)))
        
        # Apply PlaceableMixin to ItemStack (handled separately)

