"""Reachable entities and resources query module.

Provides synchronous access to reachable entities and resources via RconHandler.
No async listener needed - all operations are synchronous.

Ghosts are now included in entity queries by default (for spatial awareness).
Use include_ghosts=False in options to exclude them.
"""

from __future__ import annotations

from typing import List, Optional, Dict, Any, Union, TYPE_CHECKING

from FactoryVerse.game.factory.types import MapPosition

if TYPE_CHECKING:
    from FactoryVerse.game.agent.infra.rcon_handler import RconHandler
    from FactoryVerse.game.factory.entity.base_entity import BaseEntity


class ReachableView:
    """Unified reachable entities and resources query interface.

    Provides a single top-level object for querying both entities and resources
    within the agent's interaction range.

    Entity queries:
    - get_entity() - Get a single entity by name/criteria
    - get_entities() - Get multiple entities by name/criteria
    - get_ghosts() - Get ghost entities

    Resource queries:
    - get_resource() - Get a single resource (ore/tree/rock)
    - get_resources() - Get multiple resources

    Ghost entities are included in entity queries by default for spatial awareness.
    This prevents silent overwrites when placing entities near ghosts.

    Note: Always fetches fresh data from the game - no caching.
    """

    def __init__(
        self,
        rcon_handler: "RconHandler",
        entity_ops: "EntityOperationsAction",
        place_ops: "PlacementAction",
        walking_action: "MovementAction",
        mining_action: Optional["MiningAction"] = None,
    ):
        """Initialize ReachableView query interface.

        Args:
            rcon_handler: RCON handler for command execution
            entity_ops: Entity operations action for entity interactions
            place_ops: Placement action for placement operations
            walking_action: Movement action for navigation
            mining_action: Optional MiningAction to inject into resources for mining operations
        """
        self._rcon = rcon_handler
        self._entity_ops = entity_ops
        self._place_ops = place_ops
        self._walking_action = walking_action
        self._mining_action = mining_action

    def _fetch_fresh_entities_data(self, include_ghosts: bool = True):
        """Fetch fresh entities data via RCON (no caching).

        Args:
            include_ghosts: Whether to also fetch ghost entities (default: True)
        """
        # Fetch entities and optionally ghosts
        cmd = self._rcon.build_command("get_reachable", include_ghosts)
        data = self._rcon.execute_and_parse_json(cmd)

        entities_data = data.get("entities", [])
        ghosts_data = data.get("ghosts", []) if include_ghosts else []

        # Convert to Reachable view entities using factory
        from FactoryVerse.game.factory.entity.create_entity import create_reachable_entity

        entities_instances = []
        all_data = []

        # Process regular entities
        for entity_data in entities_data:
            try:
                entity = create_reachable_entity(
                    entity_data, self._entity_ops, self._place_ops, self._walking_action, is_ghost=False
                )
                entities_instances.append(entity)
                all_data.append(entity_data)
            except ValueError:
                # Entity type not yet migrated - skip it for now
                pass

        # Process ghost entities
        for ghost_data in ghosts_data:
            try:
                entity = create_reachable_entity(
                    ghost_data, self._entity_ops, self._place_ops, self._walking_action, is_ghost=True
                )
                entities_instances.append(entity)
                all_data.append(ghost_data)
            except ValueError:
                # Entity type not yet migrated - skip it for now
                pass

        return entities_instances, all_data

    def _fetch_fresh_resources_data(self):
        """Fetch fresh resources data via RCON (no caching)."""
        cmd = self._rcon.build_command("get_reachable", False)  # attach_ghosts=False
        data = self._rcon.execute_and_parse_json(cmd)
        return data.get("resources", [])

    # =========================================================================
    # Entity Query Methods
    # =========================================================================

    def get_entity(
        self,
        entity_name: str,
        position: Optional[MapPosition] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Optional["BaseEntity"]:
        """Get a single entity matching criteria.

        Always fetches fresh data from the game - no caching.
        Includes ghost entities by default for spatial awareness.

        Args:
            entity_name: Entity prototype name (e.g., "electric-mining-drill")
            position: Optional exact position match
            options: Optional dict with filters:
                - recipe: str - filter by recipe name
                - direction: Direction - filter by direction
                - entity_type: str - filter by Factorio entity type
                - status: str - filter by status (e.g., "working", "no-power")
                - include_ghosts: bool - whether to include ghost entities (default: True)
                - ghosts_only: bool - only return ghost entities (default: False)

        Returns:
            First matching BaseEntity instance with REACHABLE view, or None if not found
        """
        options = options or {}
        include_ghosts = options.get("include_ghosts", True)
        ghosts_only = options.get("ghosts_only", False)

        # Always fetch fresh data
        entities_instances, entities_data = self._fetch_fresh_entities_data(
            include_ghosts=include_ghosts
        )

        # Filter by name first
        matches = [
            (inst, data)
            for inst, data in zip(entities_instances, entities_data)
            if inst.name == entity_name
        ]

        # Filter by ghost status
        if ghosts_only:
            matches = [(inst, data) for inst, data in matches if inst.is_ghost]
        elif not include_ghosts:
            matches = [(inst, data) for inst, data in matches if not inst.is_ghost]

        # Filter by position if provided
        if position is not None:
            matches = [
                (inst, data) for inst, data in matches if inst.position == position
            ]

        # Apply option filters
        if "recipe" in options:
            recipe = options["recipe"]
            matches = [
                (inst, data) for inst, data in matches if data.get("recipe") == recipe
            ]

        if "direction" in options:
            direction = options["direction"]
            matches = [
                (inst, data) for inst, data in matches if inst.direction == direction
            ]

        if "entity_type" in options:
            entity_type = options["entity_type"]
            matches = [
                (inst, data)
                for inst, data in matches
                if data.get("type") == entity_type
            ]

        if "status" in options:
            status = options["status"]
            matches = [
                (inst, data) for inst, data in matches if data.get("status") == status
            ]

        return matches[0][0] if matches else None

    def get_entities(
        self,
        entity_name: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> List["BaseEntity"]:
        """Get entities matching criteria.

        Always fetches fresh data from the game - no caching.
        Includes ghost entities by default for spatial awareness.

        Args:
            entity_name: Optional entity prototype name filter
            options: Optional dict with filters (same as get_entity):
                - recipe: str - filter by recipe name
                - direction: Direction - filter by direction
                - entity_type: str - filter by Factorio entity type
                - status: str - filter by status (e.g., "working", "no-power")
                - include_ghosts: bool - whether to include ghost entities (default: True)
                - ghosts_only: bool - only return ghost entities (default: False)

        Returns:
            List of matching BaseEntity instances with REACHABLE view (may be empty)
        """
        options = options or {}
        include_ghosts = options.get("include_ghosts", True)
        ghosts_only = options.get("ghosts_only", False)

        # Always fetch fresh data
        entities_instances, entities_data = self._fetch_fresh_entities_data(
            include_ghosts=include_ghosts
        )

        # Start with all entities
        matches = [
            (inst, data) for inst, data in zip(entities_instances, entities_data)
        ]

        # Filter by ghost status
        if ghosts_only:
            matches = [(inst, data) for inst, data in matches if inst.is_ghost]
        elif not include_ghosts:
            matches = [(inst, data) for inst, data in matches if not inst.is_ghost]

        # Filter by name if provided
        if entity_name is not None:
            matches = [
                (inst, data) for inst, data in matches if inst.name == entity_name
            ]

        # Apply option filters (same logic as get_entity)
        if "recipe" in options:
            recipe = options["recipe"]
            matches = [
                (inst, data) for inst, data in matches if data.get("recipe") == recipe
            ]

        if "direction" in options:
            direction = options["direction"]
            matches = [
                (inst, data) for inst, data in matches if inst.direction == direction
            ]

        if "entity_type" in options:
            entity_type = options["entity_type"]
            matches = [
                (inst, data)
                for inst, data in matches
                if data.get("type") == entity_type
            ]

        if "status" in options:
            status = options["status"]
            matches = [
                (inst, data) for inst, data in matches if data.get("status") == status
            ]

        return [inst for inst, _ in matches]

    def get_ghosts(
        self,
        entity_name: Optional[str] = None,
    ) -> List["BaseEntity"]:
        """Get ghost entities matching criteria.

        Convenience method equivalent to get_entities with ghosts_only=True.

        Args:
            entity_name: Optional entity prototype name filter

        Returns:
            List of matching ghost BaseEntity instances with REACHABLE view
        """
        return self.get_entities(entity_name, options={"ghosts_only": True})

    # =========================================================================
    # Resource Query Methods
    # =========================================================================

    def get_resource(
        self, resource_name: str, position: Optional[MapPosition] = None
    ) -> Optional[Any]:
        """Get a single resource matching criteria.

        Always fetches fresh data from the game - no caching.

        Args:
            resource_name: Resource name (e.g., "iron-ore", "tree")
            position: Optional exact position match

        Returns:
            BaseResource instance (or appropriate subclass) with mining capability, or None if not found
        """
        from FactoryVerse.game.factory.resource.base import _create_resource_from_data

        # Always fetch fresh data
        resources_data = self._fetch_fresh_resources_data()

        matches = [data for data in resources_data if data.get("name") == resource_name]

        if position is not None:
            matches = [
                data
                for data in matches
                if data.get("position", {}).get("x") == position.x
                and data.get("position", {}).get("y") == position.y
            ]

        if matches:
            # Inject actions into resource
            return _create_resource_from_data(
                matches[0], self._mining_action, self._entity_ops, self._walking_action
            )
        return None

    def get_resources(
        self, resource_name: Optional[str] = None, resource_type: Optional[str] = None
    ) -> List[Any]:
        """Get resources matching criteria.

        Returns ResourceOrePatch for multiple ore patches of same type,
        BaseResource for single ore patches or entities.

        Always fetches fresh data from the game - no caching.

        Args:
            resource_name: Optional resource name filter (e.g., "iron-ore", "tree")
            resource_type: Optional resource type filter. Can be:
                - "ore" or "resource" - filters to ore patches (type="resource")
                - "entity" - filters to trees and rocks (type="tree" or "simple-entity")
                - "tree" - filters to trees only
                - "rock" or "simple-entity" - filters to rocks only (both accepted)
                - "resource" - filters to ore patches only (Factorio type)

        Returns:
            List[Union[ResourceOrePatch, BaseResource]]:
            - ResourceOrePatch: Multiple ore patches of same type (consolidated)
            - BaseResource: Single ore patch or entity (trees/rocks)
        """
        from FactoryVerse.game.factory.resource.base import (
            ResourceOrePatch,
            BaseResource,
            _create_resource_from_data,
        )

        # Always fetch fresh data
        resources_data = self._fetch_fresh_resources_data()

        matches = resources_data

        # Filter by name if provided
        if resource_name is not None:
            matches = [data for data in matches if data.get("name") == resource_name]

        # Filter by type if provided
        if resource_type is not None:
            from FactoryVerse.game.factory.resource.base import _agent_to_game_resource_type
            
            # Handle simplified aliases
            if resource_type == "ore":
                resource_type = "resource"
            elif resource_type == "entity":
                # Match both trees and simple-entities
                matches = [
                    data
                    for data in matches
                    if data.get("type") in ("tree", "simple-entity")
                ]
            else:
                # Convert agent-facing type to game-facing type (e.g., "rock" -> "simple-entity")
                game_resource_type = _agent_to_game_resource_type(resource_type)
                # Direct type match (resource, tree, simple-entity)
                matches = [
                    data for data in matches if data.get("type") == game_resource_type
                ]

        # Group by resource name
        resources_by_name: Dict[str, List[Dict[str, Any]]] = {}
        for data in matches:
            name = data.get("name", "")
            if name not in resources_by_name:
                resources_by_name[name] = []
            resources_by_name[name].append(data)

        # Build result list
        result: List[Union[ResourceOrePatch, BaseResource]] = []

        for name, data_list in resources_by_name.items():
            resource_type_val = data_list[0].get("type", "resource")

            from FactoryVerse.game.factory.entity.base_entity import EntityView

            # Entities (trees, rocks) are always returned as BaseResource
            if resource_type_val in ("tree", "simple-entity"):
                for data in data_list:
                    # Inject actions into each resource with REACHABLE view
                    result.append(
                        _create_resource_from_data(
                            data, self._mining_action, self._entity_ops, self._walking_action, view=EntityView.REACHABLE
                        )
                    )
            # Ore patches: consolidate if multiple, return single as BaseResource
            elif resource_type_val == "resource":
                if len(data_list) > 1:
                    # Multiple tiles of same ore type -> ResourceOrePatch
                    # Inject actions into patch with REACHABLE view
                    result.append(
                        ResourceOrePatch(
                            name, data_list, self._mining_action, self._entity_ops, self._walking_action, view=EntityView.REACHABLE
                        )
                    )
                else:
                    # Single tile -> BaseResource
                    # Inject actions into resource with REACHABLE view
                    result.append(
                        _create_resource_from_data(
                            data_list[0], self._mining_action, self._entity_ops, self._walking_action, view=EntityView.REACHABLE
                        )
                    )
            else:
                # Unknown type, return as BaseResource
                for data in data_list:
                    # Inject actions into each resource with REACHABLE view
                    result.append(
                        _create_resource_from_data(
                            data, self._mining_action, self._entity_ops, self._walking_action, view=EntityView.REACHABLE
                        )
                    )

        return result
