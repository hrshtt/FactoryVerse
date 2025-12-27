from typing import List, Optional
import math
from factoryverse.dsl.entity.base import GhostEntity
from factoryverse.agent.actions.walking import MovementAction


class GhostBuilderAction:
    _movement_action: MovementAction

    async def build_ghosts(
        self,
        ghosts: List[GhostEntity],
        area: Optional[GhostAreaFilter] = None,
        count: int = 10,
        strict: bool = False,
        label: Optional[str] = None,
    ) -> ActionResult:
        """Build tracked ghost entities in bulk.

        This is an async method that walks to ghost locations and builds them.
        Prints progress as it goes: (1/n) placed, etc.

        Args:
            ghosts: Optional list of ghost keys to build (default: all tracked ghosts)
            area: Optional area constraint (max 5x5 chunks = 160x160 tiles, default: 5x5 chunks)
            count: Max entities to build (cannot exceed 64, default: 64)
            strict: If True, validate agent has all items before building (default: True)
            label: Optional label filter - only build ghosts with matching label

        Returns:
            Result dict with:
                - built_count: int (number of ghosts built)
                - failed_count: int (number of ghosts that couldn't be built)
                - total_processed: int (total ghosts processed)
                - built_ghosts: List[GhostEntity] (ghosts that were built)
                - failed_ghosts: List[GhostEntity] (ghosts that failed)
        """
        # Step 1: Filter ghosts
        candidate_ghosts = []

        if ghosts is not None:
            # Filter by provided ghost keys
            for ghost_key in ghosts:
                if ghost_key in self.__tracked_ghosts:
                    candidate_ghosts.append(
                        (ghost_key, self.__tracked_ghosts[ghost_key])
                    )
        else:
            # Use all tracked ghosts
            for ghost_key, ghost_data in self.__tracked_ghosts.items():
                candidate_ghosts.append((ghost_key, ghost_data))

        # Filter by label if provided
        if label is not None:
            candidate_ghosts = [
                (key, ghost) for key, ghost in candidate_ghosts if ghost.label == label
            ]

        # Filter by area if provided
        if area is not None:
            filtered = []
            for ghost_key, ghost in candidate_ghosts:
                x = ghost.position.x
                y = ghost.position.y

                # Check bounding box
                if (
                    "min_x" in area
                    and "min_y" in area
                    and "max_x" in area
                    and "max_y" in area
                ):
                    if not (
                        area["min_x"] <= x <= area["max_x"]
                        and area["min_y"] <= y <= area["max_y"]
                    ):
                        continue

                # Check circular area
                elif "center_x" in area and "center_y" in area and "radius" in area:
                    center_x = area["center_x"]
                    center_y = area["center_y"]
                    radius = area["radius"]
                    dx = x - center_x
                    dy = y - center_y
                    if dx * dx + dy * dy > radius * radius:
                        continue

                filtered.append((ghost_key, ghost))
            candidate_ghosts = filtered

        # Step 2: Get agent position
        agent_pos = self._factory.get_position()

        # Step 3: Calculate distances and sort
        ghost_distances = []
        for ghost_key, ghost in candidate_ghosts:
            dx = ghost.position.x - agent_pos.x
            dy = ghost.position.y - agent_pos.y
            distance = math.sqrt(dx * dx + dy * dy)
            ghost_distances.append((distance, ghost_key, ghost))

        # Sort by distance
        ghost_distances.sort(key=lambda x: x[0])

        # Step 4: If strict=True, validate inventory
        if strict:
            # Get inventory
            inventory = self._factory.inventory.item_stacks
            inventory_dict = {item.name: item.count for item in inventory}

            # Count required items
            required = {}
            for _, ghost_key, ghost in ghost_distances[:count]:
                entity_name = ghost.name
                if entity_name:
                    required[entity_name] = required.get(entity_name, 0) + 1

            # Check if we have enough
            missing = {}
            for entity_name, needed in required.items():
                available = inventory_dict.get(entity_name, 0)
                if available < needed:
                    missing[entity_name] = needed - available

            if missing:
                return {
                    "built_count": 0,
                    "failed_count": 0,
                    "total_processed": 0,
                    "built_ghosts": [],
                    "failed_ghosts": [],
                    "error": f"Insufficient items: {missing}",
                }

        # Step 5: Simple clustering (group within reach_distance ~2.5 tiles)
        REACH_DISTANCE = 2.5
        clusters = []
        used = set()

        for distance, ghost_key, ghost in ghost_distances[:count]:
            if ghost_key in used:
                continue

            # Start new cluster
            cluster = [(ghost_key, ghost)]
            used.add(ghost_key)

            # Find nearby ghosts
            cluster_x = ghost.position.x
            cluster_y = ghost.position.y

            for other_dist, other_key, other_ghost in ghost_distances[:count]:
                if other_key in used:
                    continue

                dx = other_ghost.position.x - cluster_x
                dy = other_ghost.position.y - cluster_y
                dist = math.sqrt(dx * dx + dy * dy)

                if dist <= REACH_DISTANCE * 2:  # Allow slightly larger clusters
                    cluster.append((other_key, other_ghost))
                    used.add(other_key)

            clusters.append(cluster)

        # Step 6: Build ghosts cluster by cluster
        built_count = 0
        failed_count = 0
        built_ghosts = []
        failed_ghosts = []
        total_to_build = sum(len(cluster) for cluster in clusters)

        print(f"Building {total_to_build} ghosts in {len(clusters)} clusters...")

        for cluster_idx, cluster in enumerate(clusters, 1):
            # Calculate cluster center (average position)
            total_x = 0
            total_y = 0
            for _, ghost in cluster:
                total_x += ghost.position.x
                total_y += ghost.position.y

            center_x = total_x / len(cluster)
            center_y = total_y / len(cluster)
            cluster_center = MapPosition(x=center_x, y=center_y)

            # Walk to cluster center
            print(
                f"Cluster {cluster_idx}/{len(clusters)}: Walking to ({center_x:.1f}, {center_y:.1f})..."
            )
            await self._factory.walking.to(cluster_center, strict_goal=False)

            # Get reachable ghosts after walking
            reachable_data = self._factory.get_reachable(attach_ghosts=True)
            reachable_ghosts = reachable_data.get("ghosts", [])

            # Create position lookup for reachable ghosts
            reachable_positions = {}
            for ghost in reachable_ghosts:
                pos = ghost.get("position", {})
                if isinstance(pos, dict):
                    key = f"{pos.get('x', 0)},{pos.get('y', 0)}"
                else:
                    key = f"{getattr(pos, 'x', 0)},{getattr(pos, 'y', 0)}"
                reachable_positions[key] = ghost

            # Build ghosts in cluster
            for ghost_key, ghost in cluster:
                pos_key = f"{ghost.position.x},{ghost.position.y}"
                position = ghost.position

                # Check if ghost is reachable
                if pos_key not in reachable_positions:
                    print(f"  Ghost {ghost.name} at {pos_key} not reachable, skipping")
                    failed_count += 1
                    failed_ghosts.append(ghost)
                    continue

                # Try to build
                try:
                    result = ghost.build()

                    if result.get("success"):
                        built_count += 1
                        built_ghosts.append(ghost)
                        print(
                            f"  ({built_count}/{total_to_build}) Built {ghost.name} at {pos_key}"
                        )

                        # Remove from tracking
                        if ghost_key in self.__tracked_ghosts:
                            del self.__tracked_ghosts[ghost_key]
                    else:
                        failed_count += 1
                        failed_ghosts.append(ghost)
                        print(
                            f"  Failed to build {ghost.name} at {pos_key}: {result.get('error', 'Unknown error')}"
                        )
                except Exception as e:
                    failed_count += 1
                    failed_ghosts.append(ghost)
                    print(f"  Error building {ghost.name} at {pos_key}: {e}")

        # Save updated tracking
        self._save()

        # Summary
        print(
            f"\nBuild summary: {built_count} built, {failed_count} failed out of {total_to_build} total"
        )

        return {
            "built_count": built_count,
            "failed_count": failed_count,
            "total_processed": total_to_build,
            "built_ghosts": built_ghosts,
            "failed_ghosts": failed_ghosts,
        }
