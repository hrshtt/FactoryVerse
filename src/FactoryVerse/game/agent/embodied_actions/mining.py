"""Mining action implementation with dataclass response types.

Handles all mining-related operations: mine resources, cancel mining.
"""

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, TYPE_CHECKING
import logging

from FactoryVerse.game.factory.types import MapPosition
from FactoryVerse.game.agent.models import (
    AsyncActionResponse,
    AsyncActionCompletion,
    ActionResponse,
)

if TYPE_CHECKING:
    from ..infra.rcon_handler import RconHandler
    from ..infra.async_listener import AsyncActionListener
    from FactoryVerse.game.factory.item.base import ItemStack
    from FactoryVerse.game.agent.embodied_actions.place_entity import PlacementAction

logger = logging.getLogger(__name__)


class MiningReconciliationError(RuntimeError):
    """Mining reached a terminal transport state without causal agreement.

    ``facts`` is intentionally machine-readable so callers and live contracts
    can distinguish an engine/inventory disagreement from an ordinary action
    timeout.  A reconciliation failure is never converted to mined items.
    """

    def __init__(
        self,
        message: str,
        *,
        action_id: str = "",
        resource_name: str = "",
        position: Optional[Dict[str, float]] = None,
        facts: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.action_id = action_id
        self.resource_name = resource_name
        self.position = position
        self.facts = facts or {}


# =============================================================================
# ACTION RESPONSE TYPES
# =============================================================================


@dataclass
class MiningStarted(AsyncActionResponse):
    """Response when mining action is queued/started.

    RCON Contract: RemoteInterface.lua mine_resource.returns.immediate

    Returned immediately when mine() is called. If queued=True, the action
    is running asynchronously and completion will come via UDP.
    """

    entity_name: str = ""
    entity_position: Optional[Dict[str, float]] = None

    @property
    def resource_position(self) -> Optional[MapPosition]:
        """Get resource position as MapPosition."""
        if self.entity_position:
            return MapPosition(x=self.entity_position["x"], y=self.entity_position["y"])
        return None


@dataclass
class MiningCompleted(AsyncActionCompletion):
    """Response when mining action completes successfully.

    RCON Contract: RemoteInterface.lua mine_resource.returns.completion

    Received via UDP when mining completes. Contains the actual items obtained.
    """

    actual_products: Optional[Dict[str, int]] = None

    def __post_init__(self):
        if self.actual_products is None:
            self.actual_products = {}
        # Ensure actual_products is a dict (handle case where it might be a list or other type)
        if not isinstance(self.actual_products, dict):
            logger.warning(f"MiningCompleted.actual_products is not a dict: {type(self.actual_products)}, converting")
            if isinstance(self.actual_products, list):
                # Try to convert list of dicts to single dict
                products_dict = {}
                for item in self.actual_products:
                    if isinstance(item, dict) and "name" in item and "count" in item:
                        products_dict[item["name"]] = item["count"]
                self.actual_products = products_dict
            else:
                self.actual_products = {}

    @property
    def has_products(self) -> bool:
        """True if any products were obtained."""
        return bool(self.actual_products)

    def to_item_stacks(self, placement: Optional["PlacementAction"] = None) -> List["ItemStack"]:
        """Convert products to ItemStack list with placement injected.
        
        Always returns a list of ItemStack objects, even if empty.
        
        Args:
            placement: PlacementAction to inject into items (required for .place() to work)
            
        Returns:
            List of ItemStack objects (never None, never empty dict, always a list)
        """
        from FactoryVerse.game.factory.item.create_item import create_item_stack
        
        items = []
        
        # Ensure actual_products is a dict (handle None, empty dict, etc.)
        products = self.actual_products or {}
        if not isinstance(products, dict):
            logger.warning(f"MiningCompleted.actual_products is not a dict: {type(products)}, defaulting to empty dict")
            products = {}
        
        # Log if products dict is empty but we expect items
        if not products:
            logger.debug("MiningCompleted.actual_products is empty - no items to convert to ItemStack")
        
        # Convert each product to ItemStack
        for name, count in products.items():
            if not name or not isinstance(name, str):
                logger.warning(f"Skipping invalid product name: {name} (type: {type(name)})")
                continue
            if not isinstance(count, (int, float)) or count <= 0:
                logger.warning(f"Skipping invalid product count for {name}: {count} (type: {type(count)})")
                continue
                
            try:
                item_stack = create_item_stack(
                    name=name,
                    count=int(count),
                    placement=placement,
                    subgroup="raw-resource",
                )
                items.append(item_stack)
                logger.debug(f"Created ItemStack: {name} x{count}")
            except Exception as e:
                logger.error(f"Failed to create ItemStack for {name} (count={count}): {e}")
                # Continue processing other items even if one fails
        
        if products and not items:
            logger.warning(
                f"MiningCompleted had products {products} but no ItemStacks were created. "
                "This may indicate a format issue with the product data."
            )
        
        return items


@dataclass
class MiningCancelled(ActionResponse):
    """Response when mining action is cancelled.

    RCON Contract: RemoteInterface.lua stop_mining.returns

    Returned when stop_mining() is called or mining is interrupted.
    """

    action_id: Optional[str] = None
    items_obtained: Optional[Dict[str, int]] = None

    @property
    def was_active(self) -> bool:
        """True if there was an active mining action."""
        return self.action_id is not None


# =============================================================================
# MINING ACTION
# =============================================================================


class MiningAction:
    """Mining action implementation.

    Owns all mining logic:
    - mine(): Mine a resource with optional count limit
    - cancel(): Stop current mining operation

    All methods return structured dataclass response types for type safety.
    """

    def __init__(
        self,
        rcon_handler: "RconHandler",
        async_listener: "AsyncActionListener",
        placement: Optional["PlacementAction"] = None,
    ):
        """Initialize mining action.

        Args:
            rcon_handler: RCON handler for command execution
            async_listener: Async listener for action completion
            placement: PlacementAction for item injection (optional for now)
        """
        self._rcon = rcon_handler
        self._listener = async_listener
        self._placement = placement
        self._resource_depletion_barrier: Optional[
            Callable[..., Awaitable[Optional[Dict[str, Any]]]]
        ] = None
        self._resource_depletion_prepare: Optional[
            Callable[[str, float, float], Dict[str, Any]]
        ] = None
        self.last_causal_facts: Dict[str, Any] = {}

    def set_resource_depletion_barrier(
        self,
        barrier: Callable[
            ..., Awaitable[Optional[Dict[str, Any]]]
        ],
        prepare: Optional[Callable[[str, float, float], Dict[str, Any]]] = None,
    ) -> None:
        """Make depleted-resource completion causally fresh for later reads.

        The game action and snapshot mutation arrive on different UDP ports.
        Tier 4 installs a barrier which waits for the exact removal to become
        visible in its owned database before ``mine()`` returns to actor code.
        """
        self._resource_depletion_barrier = barrier
        self._resource_depletion_prepare = prepare

    async def mine(
        self,
        resource_name: str,
        max_count: Optional[int] = None,
        position: Optional[MapPosition] = None,
        timeout: Optional[int] = None,
    ) -> List["ItemStack"]:
        """Mine a resource.

        Args:
            resource_name: Resource prototype name (e.g., "iron-ore", "coal")
            max_count: Max items to mine (None = deplete resource)
            position: Optional position to mine at
            timeout: Optional timeout in seconds

        Returns:
            List of ItemStack objects obtained from mining with placement injected

        Raises:
            RuntimeError: If mining fails to start or times out
        """
        # Enforce 25 limit for safety
        if max_count and max_count > 25:
            logger.warning(f"Capping mining count from {max_count} to 25")
            max_count = 25

        depletion_baseline: Optional[Dict[str, Any]] = None
        if position is not None and self._resource_depletion_prepare is not None:
            depletion_baseline = self._resource_depletion_prepare(
                resource_name, float(position.x), float(position.y)
            )

        # Build and execute RCON command
        cmd = self._rcon.build_command(
            "mine_resource",
            resource_name,
            max_count,
            position,
        )
        response_dict = self._rcon.execute_and_parse_json(cmd)
        response = MiningStarted.from_dict(response_dict)

        # Check if mining started successfully
        if not response.is_queued:
            reason = response.reason or "unknown"
            raise RuntimeError(f"Failed to start mining: {reason}")

        # Wait for completion via UDP
        completion_dict = await self._listener.await_action(response, timeout=timeout)

        # Flatten 'result' dict into completion_dict if present
        # The UDP message has actual_products nested inside 'result', but
        # MiningCompleted.from_dict expects it at the top level
        if isinstance(completion_dict, dict) and 'result' in completion_dict:
            result_data = completion_dict.get('result', {})
            if isinstance(result_data, dict):
                # Merge result fields into top level (result fields take precedence)
                flattened = {**completion_dict, **result_data}
                completion_dict = flattened

        completion = MiningCompleted.from_dict(completion_dict)

        completion_position = completion_dict.get("position") or position
        structured_position: Optional[Dict[str, float]]
        if isinstance(completion_position, MapPosition):
            structured_position = {
                "x": float(completion_position.x),
                "y": float(completion_position.y),
            }
        elif isinstance(completion_position, dict):
            raw_x = completion_position.get("x")
            raw_y = completion_position.get("y")
            structured_position = (
                {"x": float(raw_x), "y": float(raw_y)}
                if isinstance(raw_x, (int, float))
                and isinstance(raw_y, (int, float))
                else None
            )
        else:
            structured_position = None

        raw_causal_facts = completion_dict.get("causal_facts") or {}
        causal_facts = dict(raw_causal_facts)
        engine_destroy_event_tick = causal_facts.get("destroy_event_tick")
        if engine_destroy_event_tick is not None:
            causal_facts["engine_destroy_event_tick"] = engine_destroy_event_tick
        self.last_causal_facts = dict(causal_facts)
        if not completion.success or completion.reason == "reconciliation_failed":
            raise MiningReconciliationError(
                "Mining completion facts did not reconcile for "
                f"{completion_dict.get('entity_name') or resource_name}",
                action_id=completion.action_id or response.action_id or "",
                resource_name=str(
                    completion_dict.get("entity_name") or resource_name
                ),
                position=structured_position,
                facts=causal_facts,
            )

        if (
            completion.success
            and completion.reason == "depleted"
            and self._resource_depletion_barrier is not None
        ):
            if isinstance(completion_position, MapPosition):
                position_x = completion_position.x
                position_y = completion_position.y
            elif isinstance(completion_position, dict):
                position_x = completion_position.get("x")
                position_y = completion_position.get("y")
            else:
                position_x = position_y = None
            if position_x is not None and position_y is not None:
                entity_name = completion_dict.get("entity_name") or resource_name
                try:
                    if self._resource_depletion_prepare is not None:
                        if engine_destroy_event_tick is None:
                            raise MiningReconciliationError(
                                "Mining completion omitted its engine destroy tick",
                                action_id=completion.action_id
                                or response.action_id
                                or "",
                                resource_name=str(entity_name),
                                position=structured_position,
                                facts=causal_facts,
                            )
                        barrier_facts = await self._resource_depletion_barrier(
                            str(entity_name),
                            float(position_x),
                            float(position_y),
                            expected_destroy_tick=engine_destroy_event_tick,
                            expected_action_id=(
                                completion.action_id or response.action_id or None
                            ),
                            baseline=depletion_baseline,
                        )
                    else:
                        barrier_facts = await self._resource_depletion_barrier(
                            str(entity_name), float(position_x), float(position_y)
                        )
                    if barrier_facts:
                        snapshot_tick = barrier_facts.get(
                            "snapshot_destroy_event_tick",
                            barrier_facts.get("destroy_event_tick"),
                        )
                        expected_action_id = (
                            completion.action_id or response.action_id or None
                        )
                        barrier_action_id = barrier_facts.get("destroy_action_id")
                        sequence = barrier_facts.get("destroy_event_sequence")
                        sequence_floor = (depletion_baseline or {}).get(
                            "entity_sequence_floor"
                        )
                        strict_barrier = self._resource_depletion_prepare is not None
                        barrier_matches = (
                            not strict_barrier
                            or (
                                snapshot_tick == engine_destroy_event_tick
                                and barrier_action_id == expected_action_id
                                and isinstance(sequence, int)
                                and isinstance(sequence_floor, int)
                                and sequence > sequence_floor
                                and barrier_facts.get(
                                    "resource_present_at_action_start"
                                )
                                is True
                            )
                        )
                        if not barrier_matches:
                            failed_facts = dict(causal_facts)
                            failed_facts["barrier_facts"] = dict(barrier_facts)
                            failed_facts["duckdb_depleted"] = False
                            self.last_causal_facts = failed_facts
                            raise MiningReconciliationError(
                                "DuckDB removal evidence does not belong to "
                                "this mining action",
                                action_id=completion.action_id
                                or response.action_id
                                or "",
                                resource_name=str(entity_name),
                                position=structured_position,
                                facts=failed_facts,
                            )
                        causal_facts.update(
                            {
                                key: value
                                for key, value in barrier_facts.items()
                                if key != "destroy_event_tick"
                            }
                        )
                    causal_facts["duckdb_depleted"] = True
                    self.last_causal_facts = dict(causal_facts)
                except TimeoutError as exc:
                    failed_facts = dict(causal_facts)
                    failed_facts["duckdb_depleted"] = False
                    self.last_causal_facts = failed_facts
                    raise MiningReconciliationError(
                        "Engine mining completed but the exact DuckDB resource "
                        "row did not reconcile",
                        action_id=completion.action_id or response.action_id or "",
                        resource_name=str(entity_name),
                        position=structured_position,
                        facts=failed_facts,
                    ) from exc

        # Log actual_products for debugging
        if completion.actual_products:
            logger.debug(f"Mining completed with products: {completion.actual_products}")
        else:
            logger.warning(
                f"Mining completed but actual_products is empty or None. "
                f"Completion dict keys: {list(completion_dict.keys()) if isinstance(completion_dict, dict) else 'N/A'}. "
                f"Reason: {completion_dict.get('reason', 'unknown') if isinstance(completion_dict, dict) else 'N/A'}. "
                f"Count: {completion_dict.get('count', 'N/A') if isinstance(completion_dict, dict) else 'N/A'}"
            )
            
            # Try to infer products from count if available (for INCREMENTAL mode)
            if isinstance(completion_dict, dict):
                count = completion_dict.get('count')
                entity_name = completion_dict.get('entity_name') or resource_name
                if count and count > 0 and entity_name:
                    logger.info(f"Inferring actual_products from count={count} for {entity_name}")
                    completion.actual_products = {entity_name: count}

        # Return items as ItemStack list with placement injected
        # Always returns a list of ItemStack objects (never None, never empty dict)
        item_stacks = completion.to_item_stacks(self._placement)
        if not isinstance(item_stacks, list):
            logger.error(f"MiningCompleted.to_item_stacks() returned non-list: {type(item_stacks)}, returning empty list")
            return []
        
        # Log if we got items but list is empty (indicates filtering issue)
        if completion.actual_products and not item_stacks:
            logger.warning(
                f"Mining had products {completion.actual_products} but to_item_stacks() returned empty list. "
                "This may indicate invalid product format or filtering issue."
            )
        
        return item_stacks

    def cancel(self) -> MiningCancelled:
        """Cancel current mining action.

        Returns:
            MiningCancelled response with cancellation status and any items obtained
        """
        cmd = self._rcon.build_command("stop_mining")
        response_dict = self._rcon.execute_and_parse_json(cmd)
        return MiningCancelled.from_dict(response_dict)
