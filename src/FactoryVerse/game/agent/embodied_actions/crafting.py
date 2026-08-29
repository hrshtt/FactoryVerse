"""Crafting action implementation.

Handles all crafting-related operations with async support via RconHandler and AsyncActionListener.
"""

from typing import List, Optional, Dict, Any, TYPE_CHECKING
from dataclasses import dataclass, field
import asyncio
import logging

from FactoryVerse.game.agent.models import AsyncActionResponse, AsyncActionCompletion
from FactoryVerse.game.factory.types import CraftingQueueStatus, CraftingQueueItem

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ..infra.rcon_handler import RconHandler
    from ..infra.async_listener import AsyncActionListener
    from FactoryVerse.game.factory.item.base import ItemStack
    from FactoryVerse.game.agent.embodied_actions.place_entity import PlacementAction


@dataclass
class CraftingStarted(AsyncActionResponse):
    """Response when crafting action is queued/started.

    RCON Contract: RemoteInterface.lua craft_enqueue.returns.immediate

    Returned immediately when craft() is called. If queued=True, the action
    is running asynchronously and completion will come via UDP.
    """

    recipe: str = ""


@dataclass
class CraftingCompleted(AsyncActionCompletion):
    """Response when crafting action completes successfully.

    RCON Contract: RemoteInterface.lua craft_enqueue.returns.completion

    Received via UDP when crafting completes. Contains the actual items crafted.
    """

    items: Optional[Dict[str, int]] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CraftingCompleted":
        """Create instance from dict, mapping 'products' to 'items' for compatibility.
        
        Handles both top-level 'products' and 'products' nested inside 'result'.
        """
        # Extract products from result if present (UDP payload structure)
        if "result" in data and isinstance(data["result"], dict):
            result = data["result"]
            if "products" in result and "items" not in data:
                data = {**data, "items": result["products"]}
        
        # Handle both 'products' (from Lua) and 'items' (preferred) at top level
        if "products" in data and "items" not in data:
            data = {**data, "items": data["products"]}
        
        return super().from_dict(data)

    def __post_init__(self):
        if self.items is None:
            self.items = {}

    @property
    def has_items(self) -> bool:
        """True if any items were crafted."""
        return bool(self.items)

    def to_item_stacks(self, placement: Optional["PlacementAction"] = None) -> List["ItemStack"]:
        """Convert crafted items to ItemStack list with placement injected.
        
        Always returns a list of ItemStack objects, even if empty.
        
        Args:
            placement: PlacementAction to inject into items (required for .place() to work)
            
        Returns:
            List of ItemStack objects (never None, never empty dict, always a list)
        """
        from FactoryVerse.game.factory.item.create_item import create_item_stack
        
        stacks = []
        
        # Ensure items is a dict (handle None, empty dict, etc.)
        items = self.items or {}
        if not isinstance(items, dict):
            logger.warning(f"CraftingCompleted.items is not a dict: {type(items)}, defaulting to empty dict")
            items = {}
        
        # Convert each item to ItemStack
        for name, count in items.items():
            if not name or not isinstance(name, str):
                logger.warning(f"Skipping invalid item name: {name}")
                continue
            if not isinstance(count, (int, float)) or count <= 0:
                logger.warning(f"Skipping invalid item count for {name}: {count}")
                continue
                
            try:
                item_stack = create_item_stack(
                    name=name,
                    count=int(count),
                    placement=placement,
                    subgroup="intermediate-product",
                )
                stacks.append(item_stack)
            except Exception as e:
                logger.error(f"Failed to create ItemStack for {name} (count={count}): {e}")
                # Continue processing other items even if one fails
        
        return stacks


@dataclass
class CraftPrediction:
    """Derived at enqueue from recipe energy at crafting speed 1, serially
    (TURN_CONTRACT §7.1) — arithmetic, never extrapolation. The turn report
    reads these through ``CraftingAction.take_predictions()`` and prints
    predicted against actual."""

    recipe: str
    count: int
    predicted_completion_tick: int
    enqueued_tick: int
    per_craft_ticks: float


class CraftingAction:
    """Crafting action implementation.

    Owns all crafting logic:
    - craft(): Craft a recipe asynchronously (waits for completion)
    - enqueue(): Queue a recipe for crafting (returns immediately)
    - dequeue(): Cancel queued crafting
    - status(): Get current crafting status
    """

    def __init__(
        self,
        rcon_handler: "RconHandler",
        async_listener: "AsyncActionListener",
        placement: Optional["PlacementAction"] = None,
    ):
        """Initialize crafting action.

        Args:
            rcon_handler: RCON handler for command execution
            async_listener: Async listener for action completion
            placement: PlacementAction for item injection (optional for now)
        """
        self._rcon = rcon_handler
        self._listener = async_listener
        self._placement = placement
        self._predictions: List[CraftPrediction] = []

    # ---- predictions (TURN_CONTRACT §7.1) ------------------------------------

    @property
    def predictions(self) -> List[CraftPrediction]:
        """Predictions recorded at enqueue and not yet handed to a report."""
        return list(self._predictions)

    def take_predictions(self) -> List[CraftPrediction]:
        """Hand the pending predictions to the turn report and clear them.
        This is the hook the report calls once per turn."""
        out, self._predictions = self._predictions, []
        return out

    @staticmethod
    def _recipe_energy(recipe: str) -> Optional[float]:
        """Recipe energy in seconds at speed 1, from the prototype dump."""
        try:
            from FactoryVerse.game.factory.prototype_data import get_prototype_manager

            raw = get_prototype_manager().get_raw_data()
            proto = (raw.get("recipe") or {}).get(recipe)
            if proto is None:
                return None
            return float(proto.get("energy_required", 0.5))
        except Exception:
            return None

    def _game_tick(self) -> Optional[int]:
        try:
            raw = self._rcon.execute("rcon.print(game.tick)")
            return int(str(raw).strip()) if raw is not None and str(raw).strip() else None
        except Exception:
            return None

    def _predict(self, recipe: str, count: int, response: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        energy = self._recipe_energy(recipe)
        if energy is None:
            return None
        queued = int(response.get("count_queued", response.get("count", count)) or count)
        per_craft = energy * 60.0
        # Serial queue: what is already queued drains first.
        ahead = 0.0
        try:
            for item in self.status().get("queue", []):
                if item.get("recipe") == recipe and item.get("count") == queued:
                    continue
                e = self._recipe_energy(item.get("recipe", ""))
                ahead += (e or 0.0) * 60.0 * int(item.get("count", 0))
        except Exception:
            ahead = 0.0
        now = self._game_tick() or 0
        total = int(round(ahead + per_craft * queued))
        pred = CraftPrediction(recipe, queued, now + total, now, per_craft)
        self._predictions.append(pred)
        return {
            "per_craft_ticks": per_craft,
            "queue_ticks_ahead": int(round(ahead)),
            "ticks_until_done": total,
            "predicted_completion_tick": pred.predicted_completion_tick,
        }

    def enqueue(self, recipe: str, count: int = 1) -> Dict[str, Any]:
        """Enqueue a recipe for crafting.

        Args:
            recipe: Recipe name to craft
            count: Number of times to craft

        Returns:
            Response dict with queued status. If fewer crafts were queued than
            requested (ingredient-limited), the dict carries a 'message'
            explaining the partial queue (count_queued < count_requested).

        Raises:
            RuntimeError: Same structured failure modes as craft() —
                unknown recipe / locked recipe / missing ingredients
                (name + have + need) / invalid count / queue full.
        """
        cmd = self._rcon.build_command("craft_enqueue", recipe, count)
        response = self._rcon.execute_and_parse_json(cmd)
        if isinstance(response, dict) and response.get("success", response.get("queued", True)):
            prediction = self._predict(recipe, count, response)
            if prediction:
                response = {**response, "prediction": prediction}
        return response

    def list_recipes(
        self,
        name_filter: Optional[str] = None,
        hand_craftable: Optional[bool] = None,
        category: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """The recipe catalog, as the crafting screen lists it (HUD plan §2 as amended).

        A read; nothing is queued. Each entry: ``name``, ``category``,
        ``energy`` (seconds at speed 1), ``ingredients``, ``hand_craftable``
        (a character can make it — smelting is machine-only, the classic
        mistake), and ``craftable_now`` as an annotation (ingredients on hand),
        never as a filter, so the catalog stays a catalog.

        Args:
            name_filter: substring match on the recipe name
            hand_craftable: True → only hand-craftable, False → only machine-only
            category: exact crafting category (e.g. "crafting", "smelting")
        """
        from FactoryVerse.game.factory.prototypes import get_recipe_prototypes

        cmd = self._rcon.build_command("get_recipes", category)
        data = self._rcon.execute_and_parse_json(cmd)
        if isinstance(data, dict) and data.get("error"):
            raise ValueError(f"{data['error']}; valid categories: {data.get('valid_categories')}")
        recipes = data if isinstance(data, list) else data.get("recipes", [])
        protos = get_recipe_prototypes()
        inventory_counts: Dict[str, int] = {}
        try:
            inv = self._rcon.execute_and_parse_json(self._rcon.build_command("get_inventory_items"))
            for stack in inv or []:
                inventory_counts[stack["name"]] = inventory_counts.get(stack["name"], 0) + int(stack["count"])
        except Exception:
            inventory_counts = {}
        out: List[Dict[str, Any]] = []
        for r in recipes:
            name = r.get("name", "")
            if name_filter and name_filter not in name:
                continue
            hand = bool(protos.is_handcraftable(name))
            if hand_craftable is not None and hand != hand_craftable:
                continue
            ingredients = r.get("ingredients") or []
            craftable_now = hand and all(
                inventory_counts.get(i.get("name"), 0) >= int(i.get("amount", 0))
                for i in ingredients
            )
            out.append({
                "name": name,
                "category": r.get("category"),
                "energy": r.get("energy"),
                "ingredients": ingredients,
                "hand_craftable": hand,
                "craftable_now": craftable_now,
            })
        out.sort(key=lambda x: x["name"])
        return out

    def dequeue(self, recipe: str, count: Optional[int] = None) -> Dict[str, Any]:
        """Cancel queued crafting.

        Args:
            recipe: Recipe name to cancel
            count: Number to cancel (None = all)

        Returns:
            Response dict with cancellation status
        """
        cmd = self._rcon.build_command("craft_dequeue", recipe, count)
        return self._rcon.execute_and_parse_json(cmd)

    def status(self) -> CraftingQueueStatus:
        """Get current crafting queue status with full details.

        Returns:
            CraftingQueueStatus with queue items, size, and progress
            
        Example:
            ```python
            status = crafting.status()
            print(f"Queue size: {status.queue_size}")
            print(f"Progress: {status.progress:.1%}")
            for item in status.queue:
                print(f"  {item.recipe} x{item.count} (index {item.index})")
            ```
        """
        cmd = self._rcon.build_command("get_crafting_queue")
        data = self._rcon.execute_and_parse_json(cmd)
        
        # Parse queue items
        queue_items = []
        for item_data in data.get("queue", []):
            queue_items.append(CraftingQueueItem(
                index=item_data.get("index", 0),
                recipe=item_data.get("recipe", ""),
                count=item_data.get("count", 0),
                prerequisite=item_data.get("prerequisite", False),
            ))
        
        return CraftingQueueStatus(
            queue=queue_items,
            queue_size=data.get("queue_size", 0),
            progress=data.get("progress", 0.0),
        )
