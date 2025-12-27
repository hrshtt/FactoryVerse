from typing import Optional


class PlayingFactory:
    """Represents an active gameplay session for an agent."""

    _game_data_sync: Optional["GameDataSyncService"]

    def __init__(
        self,
        rcon_client: "RCONClient",
        agent_id: str,
        recipes: Recipes,
        tech_tree: TechTree,
        udp_dispatcher: Optional[UDPDispatcher] = None,
        agent_udp_port: Optional[int] = None,
    ):
        """
        Initialize PlayingFactory.

        Args:
            rcon_client: RCON client for remote interface calls
            agent_id: Agent ID (e.g., 'agent_1')
            recipes: Recipes instance
            tech_tree: TechTree instance
            udp_dispatcher: Optional UDPDispatcher for shared port mode (deprecated, use agent_udp_port instead)
            agent_udp_port: Optional UDP port for agent-specific async actions. If provided, agent owns this port completely.
        """
        self._rcon = rcon_client
        self._agent_id = agent_id
        self.agent_commands = AgentCommands(agent_id)
        self.recipes = recipes
        self.tech_tree = tech_tree
        self._async_listener = AsyncActionListener(
            udp_dispatcher=udp_dispatcher, agent_port=agent_udp_port
        )
        self._ghost_manager = GhostManager(self, agent_id=agent_id)
        self._duckdb_connection = None
        self._game_data_sync = None

        # Initialize action wrappers
        self._walking = WalkingAction(self)
        self._crafting = CraftingAction(self)
        self._mining = MiningAction(self)
        self._research = ResearchAction(self)
        self._inventory = AgentInventory(self)

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def walking(self) -> "WalkingAction":
        """Walking action wrapper."""
        return self._walking

    @property
    def crafting(self) -> "CraftingAction":
        """Crafting action wrapper."""
        return self._crafting

    @property
    def mining(self) -> "MiningAction":
        """Mining action wrapper."""
        return self._mining

    @property
    def research(self) -> "ResearchAction":
        """Research action wrapper."""
        return self._research

    @property
    def inventory(self) -> "AgentInventory":
        """Agent inventory helper with methods for querying and shaping items."""
        return self._inventory

    @property
    def reachable_entities(self) -> "ReachableEntities":
        """Get reachable entities accessor."""
        if not hasattr(self, "_reachable_entities"):
            self._reachable_entities = ReachableEntities(self)
        return self._reachable_entities

    @property
    def reachable_resources(self) -> "ReachableResources":
        """Get reachable resources accessor."""
        if not hasattr(self, "_reachable_resources"):
            self._reachable_resources = ReachableResources(self)
        return self._reachable_resources

    @property
    def map_db(self) -> "_DuckDBAccessor":
        """Get DuckDB map database accessor for read-only entity queries.

        Returns RemoteViewEntity instances that can be inspected and used for
        planning, but cannot be mutated (no pickup, add_fuel, etc.).

        Requires DuckDB to be loaded first.

        Example:
            >>> drills = map_db.get_entities('''
            ...     SELECT * FROM map_entity me
            ...     JOIN mining_drill md ON me.entity_key = md.entity_key
            ...     WHERE entity_name = 'burner-mining-drill'
            ... ''')
            >>> for drill in drills:
            ...     print(drill.output_position)

        Raises:
            RuntimeError: If DuckDB connection not initialized
        """
        if not hasattr(self, "_map_db_accessor"):
            if self._duckdb_connection is None:
                raise RuntimeError(
                    "DuckDB not loaded. Load snapshots first to enable map_db queries."
                )
            self._map_db_accessor = _DuckDBAccessor(self._duckdb_connection)
        return self._map_db_accessor

    def update_recipes(self) -> None:
        cmd = self._build_command("get_recipes")
        result = self.execute(cmd)
        Recipes = Recipes(json.loads(result))
        self.recipes = Recipes

    # ========================================================================
    # ASYNC: Walking
    # ========================================================================

    def walk_to(
        self,
        goal: Union[Dict[str, float], "MapPosition"],
        strict_goal: bool = False,
        options: Optional[Dict] = None,
    ) -> WalkAsyncResponse:
        """Walk the agent to a target position using pathfinding.

        RCON Contract: RemoteInterface.lua walk_to

        Args:
            goal: Target position {x, y} or MapPosition object
            strict_goal: If true, fail if exact position unreachable
            options: Additional pathfinding options

        Returns:
            WalkAsyncResponse with {queued, action_id}
        """
        if options is None:
            options = {}
        # Convert MapPosition to dict if needed
        if hasattr(goal, "x") and hasattr(goal, "y"):
            goal = {"x": goal.x, "y": goal.y}
        cmd = self._build_command("walk_to", goal, strict_goal, options)
        return self._execute_and_parse_json(cmd)

    def stop_walking(self) -> AsyncActionResponse:
        """Immediately stop the agent's current walking action."""
        cmd = self._build_command("stop_walking")
        return self._execute_and_parse_json(cmd)

    # ========================================================================
    # ASYNC: Mining
    # ========================================================================

    def mine_resource(
        self, resource_name: str, max_count: Optional[int] = None
    ) -> MineAsyncResponse:
        """Mine a resource within reach of the agent.

        RCON Contract: RemoteInterface.lua mine_resource

        Args:
            resource_name: Resource prototype name (e.g., 'iron-ore', 'coal', 'stone')
            max_count: Max items to mine (None = deplete resource)

        Returns:
            MineAsyncResponse with {queued, action_id, entity_name, entity_position}
        """
        cmd = self._build_command("mine_resource", resource_name, max_count)
        return self._execute_and_parse_json(cmd)

    def stop_mining(self) -> AsyncActionResponse:
        """Immediately stop the agent's current mining action."""
        cmd = self._build_command("stop_mining")
        return self._execute_and_parse_json(cmd)

    # ========================================================================
    # ASYNC: Crafting
    # ========================================================================

    def craft_enqueue(self, recipe_name: str, count: int = 1) -> CraftAsyncResponse:
        """Queue a recipe for hand-crafting.

        RCON Contract: RemoteInterface.lua craft_enqueue

        Args:
            recipe_name: Recipe name to craft
            count: Number of times to craft the recipe

        Returns:
            CraftAsyncResponse with {queued, action_id, recipe, count}
        """
        if not self.recipes[recipe_name].is_hand_craftable():
            raise ValueError(f"Recipe {recipe_name} is not hand-craftable")
        if not self.recipes[recipe_name].enabled:
            raise ValueError(
                f"Recipe {recipe_name} is not enabled, try researching technology first"
            )
        cmd = self._build_command("craft_enqueue", recipe_name, count)
        return self._execute_and_parse_json(cmd)

    def craft_dequeue(
        self, recipe_name: str, count: Optional[int] = None
    ) -> ActionResult:
        """Cancel queued crafting for a recipe.

        RCON Contract: RemoteInterface.lua craft_dequeue

        Args:
            recipe_name: Recipe name to cancel
            count: Number to cancel (None = all)

        Returns:
            ActionResult with {success, cancelled_count}
        """
        cmd = self._build_command("craft_dequeue", recipe_name, count)
        return self._execute_and_parse_json(cmd)

    # ========================================================================
    # SYNC: Entity Operations
    # ========================================================================

    def set_entity_recipe(
        self,
        entity_name: str,
        position: Optional[Union[Dict[str, float], "MapPosition"]] = None,
        recipe_name: Optional[str] = None,
    ) -> ActionResult:
        """Set the recipe for a machine (assembler, furnace, chemical plant).

        RCON Contract: RemoteInterface.lua set_entity_recipe

        Args:
            entity_name: Entity prototype name
            position: Entity position (None = nearest)
            recipe_name: Recipe to set (None = clear)

        Returns:
            ActionResult with {success, entity_name, position, recipe}
        """
        cmd = self._build_command(
            "set_entity_recipe", entity_name, position, recipe_name
        )
        return self._execute_and_parse_json(cmd)

    def set_entity_filter(
        self,
        entity_name: str,
        position: Optional[Union[Dict[str, float], "MapPosition"]] = None,
        inventory_type: str = "input",
        filter_index: Optional[int] = None,
        filter_item: Optional[str] = None,
    ) -> ActionResult:
        """Set an inventory filter on an entity (inserter, container with filters).

        Args:
            entity_name: Entity prototype name
            position: Entity position (None = nearest)
            inventory_type: Inventory type to filter
            filter_index: Slot index (None = first slot)
            filter_item: Item to filter (None = clear)
        """
        cmd = self._build_command(
            "set_entity_filter",
            entity_name,
            position,
            inventory_type,
            filter_index,
            filter_item,
        )
        return self._execute_and_parse_json(cmd)

    def set_inventory_limit(
        self,
        entity_name: str,
        position: Optional[Union[Dict[str, float], "MapPosition"]] = None,
        inventory_type: str = "chest",
        limit: Optional[int] = None,
    ) -> ActionResult:
        """Set the inventory bar limit on a container.

        Args:
            entity_name: Entity prototype name
            position: Entity position (None = nearest)
            inventory_type: Inventory type to limit
            limit: Slot limit (None = no limit)
        """
        cmd = self._build_command(
            "set_inventory_limit", entity_name, position, inventory_type, limit
        )
        return self._execute_and_parse_json(cmd)

    def take_inventory_item(
        self,
        entity_name: str,
        position: Optional[Union[Dict[str, float], "MapPosition"]] = None,
        inventory_type: str = "chest",
        item_name: str = "",
        count: Optional[int] = None,
    ) -> List[ItemStack]:
        """Take items from an entity's inventory into the agent's inventory.

        Args:
            entity_name: Entity prototype name
            position: Entity position (None = nearest)
            inventory_type: Inventory type to take from
            item_name: Item name to take
            count: Count to take (None = all available)

        Returns:
            List of ItemStack objects representing the items actually taken
        """
        cmd = self._build_command(
            "take_inventory_item",
            entity_name,
            position,
            inventory_type,
            item_name,
            count,
        )
        result = self._execute_and_parse_json(cmd)
        return [ItemStack(name=result["name"], count=result["count"])]

    def put_inventory_item(
        self,
        entity_name: str,
        position: Optional[Union[Dict[str, float], "MapPosition"]] = None,
        inventory_type: str = "chest",
        item_name: str = "",
        count: int = 1,
    ) -> ActionResult:
        """Put items from the agent's inventory into an entity's inventory.

        Args:
            entity_name: Entity prototype name
            position: Entity position (None = nearest)
            inventory_type: Inventory type to put into
            item_name: Item name to put
            count: Count to put

        Returns:
            ActionResult TypedDict
        """
        cmd = self._build_command(
            "put_inventory_item",
            entity_name,
            position,
            inventory_type,
            item_name,
            count,
        )
        return self._execute_and_parse_json(cmd)

    # ========================================================================
    # SYNC: Placement
    # ========================================================================

    def place_entity(
        self,
        entity_name: str,
        position: Union[Dict[str, float], "MapPosition"],
        direction: Optional[Direction] = None,
        ghost=False,
        label: Optional[str] = None,
    ) -> ActionResult:
        """Place an entity from the agent's inventory onto the map.

        Args:
            entity_name: Entity prototype name to place
            position: MapPosition to place entity
            direction: Optional direction for placement
            ghost: Whether to place as ghost entity (default: False)
            label: Optional label for ghost entities (Python-only, for grouping/staging)

        Returns:
            Result dict with success, position, entity_name, etc.
        """
        # Convert MapPosition to dict if needed
        if hasattr(position, "x") and hasattr(position, "y"):
            position = {"x": position.x, "y": position.y}

        # Convert Direction enum to int if needed
        if direction is not None and isinstance(direction, Direction):
            direction = direction.value

        cmd = self._build_command(
            "place_entity", entity_name, position, direction, ghost
        )
        result = self._execute_and_parse_json(cmd)

        # Track ghost if placed
        if ghost and result.get("success"):
            pos = result.get("position", position)
            self._ghost_manager.add_ghost(
                position=pos,
                entity_name=entity_name,
                label=label,
                placed_tick=result.get("tick", 0),
            )
        elif not ghost and result.get("success"):
            # If placing a real entity, check if we're replacing a tracked ghost
            # Note: position here might be dict or MapPosition, GhostManager handles both
            if self._ghost_manager.remove_ghost(
                position=position, entity_name=entity_name
            ):
                logger.warning(
                    f"Ghost at {position} for {entity_name} replaced by real entity."
                )

        return result

    def inspect_entity(
        self,
        name: str,
        position: Optional[Union[Dict[str, float], "MapPosition"]] = None,
    ) -> EntityInspectionData:
        """Inspect an entity's state.

        Args:
            name: Entity prototype name
            position: MapPosition to inspect (None = nearest)

        Returns:
            EntityInspectionData TypedDict
        """
        cmd = self._build_command("inspect_entity", name, position)
        return self._execute_and_parse_json(cmd)

    def pickup_entity(
        self,
        entity_name: str,
        position: Optional[Union[Dict[str, float], "MapPosition"]] = None,
    ) -> List["ItemStack"]:
        """Pick up an entity from the map into the agent's inventory.

        Args:
            entity_name: Entity prototype name to pick up
            position: Entity position (None = nearest)

        Returns:
            List of ItemStack objects representing items added to inventory
        """
        from FactoryVerse.dsl.item.base import ItemStack

        cmd = self._build_command("pickup_entity", entity_name, position)
        result = self._execute_and_parse_json(cmd)

        if result.get("success") and result.get("item_name"):
            return [ItemStack(name=result["item_name"], count=result.get("count", 1))]
        return []

    def remove_ghost(self, entity_name: str, position: MapPosition) -> ActionResult:
        """Remove a ghost entity from the map.

        Args:
            entity_name: Entity prototype name to remove
            position: Entity position

        Returns:
            Result dict with success status
        """
        # Convert MapPosition to dict if needed
        if hasattr(position, "x") and hasattr(position, "y"):
            pos_dict = {"x": position.x, "y": position.y}
        else:
            pos_dict = position

        cmd = self._build_command("remove_ghost", entity_name, pos_dict)
        result = self._execute_and_parse_json(cmd)

        # Remove from tracking if successful
        if result.get("success"):
            self._ghost_manager.remove_ghost(position=pos_dict, entity_name=entity_name)

        return result

    # ========================================================================
    # SYNC: Movement
    # ========================================================================

    def teleport(
        self, position: Union[Dict[str, float], "MapPosition"]
    ) -> ActionResult:
        """Instantly teleport the agent to a position.

        RCON Contract: RemoteInterface.lua teleport

        Args:
            position: Target position

        Returns:
            ActionResult with {success, position}
        """
        cmd = self._build_command("teleport", position)
        return self._execute_and_parse_json(cmd)

    # ========================================================================
    # QUERIES
    # ========================================================================

    def inspect(self, attach_state: bool = False) -> AgentInspectionData:
        """Get current agent state and position.

        RCON Contract: RemoteInterface.lua inspect

        Args:
            attach_state: Include processed agent activity state (walking, mining, crafting)

        Returns:
            AgentInspectionData with {agent_id, tick, position, state?}
        """
        cmd = self._build_command("inspect", attach_state)
        return self._execute_and_parse_json(cmd)

    def inspect_entity(
        self, entity_name: str, position: MapPosition
    ) -> EntityInspectionData:
        """Get comprehensive volatile state for a specific entity.

        RCON Contract: RemoteInterface.lua inspect_entity

        Args:
            entity_name: Entity prototype name
            position: Entity position

        Returns:
            EntityInspectionData with status, recipe, progress, inventories, energy, held_item, etc.
            Not all fields present for all entity types.

        Raises:
            RuntimeError: If the remote call fails or returns an error
        """
        cmd = self._build_command(
            "inspect_entity", entity_name, {"x": position.x, "y": position.y}
        )
        return self._execute_and_parse_json(cmd)

    def get_position(self) -> MapPosition:
        """Get current agent position.

        Returns:
            MapPosition of the agent
        """
        cmd = self._build_command("get_position")
        result = self._execute_and_parse_json(cmd)
        return MapPosition(x=result["x"], y=result["y"])

    def get_placement_cues(
        self, entity_name: str, resource_name: Optional[str] = None
    ) -> PlacementCuesResponse:
        """Get placement information for an entity type.

        RCON Contract: RemoteInterface.lua get_placement_cues

        Args:
            entity_name: Entity prototype name
            resource_name: Optional resource name to filter by (e.g., "copper-ore", "iron-ore")

        Returns:
            PlacementCuesResponse with entity_name, collision_box, tile_width, tile_height,
            positions (all valid), reachable_positions (within build distance)
        """
        cmd = self._build_command("get_placement_cues", entity_name)
        data = self._execute_and_parse_json(cmd)

        # Filter by resource_name if specified
        if resource_name:
            data["positions"] = [
                cue
                for cue in data.get("positions", [])
                if cue.get("resource_name") == resource_name
            ]
            data["reachable_positions"] = [
                cue
                for cue in data.get("reachable_positions", [])
                if cue.get("resource_name") == resource_name
            ]

        return data

    def get_chunks_in_view(self) -> Dict[str, Any]:
        """Get list of map chunks currently visible/charted by the agent.

        RCON Contract: RemoteInterface.lua get_chunks_in_view

        Returns:
            Dict with {chunks: [{x, y}, ...]}
        """
        cmd = self._build_command("get_chunks_in_view")
        return self._execute_and_parse_json(cmd)

    def get_recipes(self, category: Optional[str] = None) -> Dict[str, Any]:
        """Get available recipes for the agent's force.

        RCON Contract: RemoteInterface.lua get_recipes

        Args:
            category: Filter by category (None = all)

        Returns:
            Dict with {recipes: [...]}
        """
        cmd = self._build_command("get_recipes", category)
        return self._execute_and_parse_json(cmd)

    def get_technologies(self, only_available: bool = False) -> Dict[str, Any]:
        """Get technologies for the agent's force.

        RCON Contract: RemoteInterface.lua get_technologies

        Args:
            only_available: Only show researchable techs

        Returns:
            Dict with {technologies: [...]}
        """
        cmd = self._build_command("get_technologies", only_available)
        return self._execute_and_parse_json(cmd)

    # ========================================================================
    # RESEARCH
    # ========================================================================

    def enqueue_research(self, technology_name: str) -> ActionResult:
        """Start researching a technology.

        RCON Contract: RemoteInterface.lua enqueue_research

        Args:
            technology_name: Technology to research

        Returns:
            ActionResult with {success, technology}
        """
        cmd = self._build_command("enqueue_research", technology_name)
        return self._execute_and_parse_json(cmd)

    def cancel_current_research(self) -> ActionResult:
        """Cancel the currently active research.

        RCON Contract: RemoteInterface.lua cancel_current_research

        Returns:
            ActionResult with {success}
        """
        cmd = self._build_command("cancel_current_research")
        return self._execute_and_parse_json(cmd)

    def get_research_queue(self) -> ResearchStatus:
        """Get current research queue with progress information.

        RCON Contract: RemoteInterface.lua get_research_queue

        Returns:
            ResearchStatus with {queue, queue_length, current_research, tick}
        """
        cmd = self._build_command("get_research_queue")
        return self._execute_and_parse_json(cmd)

    # ========================================================================
    # REACHABILITY
    # ========================================================================

    def get_reachable(self, attach_ghosts: bool = True) -> ReachableSnapshotData:
        """Get full reachable snapshot with complete entity data.

        RCON Contract: RemoteInterface.lua get_reachable

        Args:
            attach_ghosts: Whether to include ghosts in response (default: True)

        Returns:
            ReachableSnapshotData with {entities, resources, ghosts?, agent_position, tick}
            - entities: List of ReachableEntityData
            - resources: List of ReachableResourceData
            - ghosts: List of ReachableGhostData (only if attach_ghosts=True)
        """
        cmd = self._build_command("get_reachable", attach_ghosts)
        return self._execute_and_parse_json(cmd)

    @property
    def ghosts(self) -> GhostManager:
        """Get the ghost manager for this factory.

        Returns:
            GhostManager instance for managing tracked ghosts
        """
        return self._ghost_manager

    def _get_charted_chunks(self) -> List[tuple[int, int]]:
        """Query game for list of charted chunks via RCON.

        Returns:
            List of (chunk_x, chunk_y) tuples for all charted chunks
        """
        if not self._rcon:
            logger.warning("No RCON client available, cannot query charted chunks")
            return []

        try:
            # Query game for charted chunks
            cmd = "/c local chunks = {}; for chunk in game.surfaces[1].get_chunks() do if game.forces.player.is_chunk_charted(1, chunk) then table.insert(chunks, {x=chunk.x, y=chunk.y}) end end; rcon.print(helpers.table_to_json(chunks))"
            result = self._rcon.send_command(cmd)
            chunks_data = json.loads(result)

            # Convert to list of tuples
            charted = [(int(c["x"]), int(c["y"])) for c in chunks_data]
            logger.info(f"Found {len(charted)} charted chunks")
            return charted
        except Exception as e:
            logger.error(f"Failed to query charted chunks: {e}", exc_info=True)
            return []

    @property
    def duckdb_connection(self):
        """Get the DuckDB connection.

        Returns:
            DuckDB connection object, or None if not loaded
        """
        return self._duckdb_connection

    @property
    def game_data_sync(self) -> Optional["GameDataSyncService"]:
        """Get the game data sync service.

        Returns:
            GameDataSyncService instance, or None if not initialized
        """
        return self._game_data_sync

    # ========================================================================
    # DEBUG
    # ========================================================================

    def _inspect_state(self) -> str:
        """Get raw agent state object (for debugging)."""
        cmd = self._build_command("inspect_state")
        return self.execute(cmd)
