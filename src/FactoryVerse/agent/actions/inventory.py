from typing import List, Optional, Union, Literal, Dict, TYPE_CHECKING
from FactoryVerse.factory.item.base import ItemStack, Item, PlaceableItem
from FactoryVerse.factory.item.create_item import create_item, create_item_stack
from ..infra.rcon_handler import RconHandler

if TYPE_CHECKING:
    from FactoryVerse.agent.actions.place_entity import PlacementAction


class AgentInventory:
    """Represents the agent's inventory with helper methods for querying and shaping items.

    This is not an action class (doesn't mutate state), but provides helper methods
    to shape inventory items and stacks for downstream actions.
    """

    def __init__(self, rcon_handler: RconHandler, placement: "PlacementAction"):
        self._rcon = rcon_handler
        self._placement = placement

    def _get_inventory_items(self) -> List[ItemStack]:
        """Get agent's main inventory contents.

        RCON Contract: RemoteInterface.lua get_inventory_items

        Returns:
            List of ItemStack objects with placement action injected
        """
        cmd = self._rcon.build_command("get_inventory_items")
        response = self._rcon.execute_and_parse_json(cmd)
        return [
            create_item_stack(name=k, count=v, placement=self._placement)
            for k, v in response.items()
        ]

    @property
    def item_stacks(self) -> List[ItemStack]:
        """Get agent inventory as list of ItemStack objects.

        Equivalent to the old get_inventory_items() top-level function.
        """
        return self._get_inventory_items()

    def check_total(self, item_name: str) -> int:
        """Get total count of an item across all stacks.

        Args:
            item_name: Name of the item to count

        Returns:
            Total count of the item in inventory
        """
        return sum(stack.count for stack in self.item_stacks if stack.name == item_name)

    def get_item(self, item_name: str) -> Optional[Union["Item", "PlaceableItem"]]:
        """Get a single Item or PlaceableItem instance for the given item name.

        Args:
            item_name: Name of the item

        Returns:
            Item or PlaceableItem instance with placement injected, or None if not in inventory
        """
        if self.check_total(item_name) == 0:
            return None

        return create_item(item_name, placement=self._placement)

    def create_item_stacks(
        self,
        item_name: str,
        count: Union[int, Literal["half", "full"]],
        number_of_stacks: Union[int, Literal["max"]] = "max",
        strict: bool = False,
    ) -> List[ItemStack]:
        """Get item stacks for a specific item.

        Args:
            item_name: Name of the item
            count: Count per stack (int), "half" for half stack, or "full" for full stack
            number_of_stacks: Number of stacks to return, or "max" for all possible stacks (default: "max")
            strict: If True, raises exception when insufficient items. If False, returns all possible.

        Returns:
            List of ItemStack instances

        Raises:
            ValueError: If strict=True and insufficient items available
        """
        total_available = self.check_total(item_name)

        # Determine count per stack first (needed for validation)
        if count == "half":
            # Get stack size from item prototype
            item = self.get_item(item_name)
            if item:
                stack_size = item.stack_size
                count_per_stack = stack_size // 2
            else:
                # Fallback to default
                count_per_stack = 25
        elif count == "full":
            # Get stack size from item prototype
            item = self.get_item(item_name)
            if item:
                count_per_stack = item.stack_size
            else:
                # Fallback to default
                count_per_stack = 50
        else:
            count_per_stack = count

        # Early return if no items available
        if total_available == 0:
            if strict and isinstance(number_of_stacks, int) and number_of_stacks > 0:
                raise ValueError(f"No {item_name} available in inventory")
            return []

        # Validate if requested count exceeds available (strict mode)
        if strict and count_per_stack > total_available:
            raise ValueError(
                f"Insufficient {item_name}: requested count {count_per_stack} exceeds available {total_available}"
            )

        # Determine number of stacks
        if number_of_stacks == "max":
            # Calculate how many stacks we can make
            max_stacks = total_available // count_per_stack
            number_of_stacks = max_stacks
            # If strict and we can't make at least one stack, raise exception
            if strict and max_stacks == 0:
                raise ValueError(
                    f"Insufficient {item_name}: cannot make even one stack of {count_per_stack}, available {total_available}"
                )
        else:
            # Validate if we have enough
            required = count_per_stack * number_of_stacks
            if strict and required > total_available:
                raise ValueError(
                    f"Insufficient {item_name}: required {required}, available {total_available}"
                )
            # Cap at available (if not strict, give all possible)
            if not strict:
                max_possible = total_available // count_per_stack
                number_of_stacks = min(number_of_stacks, max_possible)

        # Ensure number_of_stacks is non-negative
        number_of_stacks = max(0, number_of_stacks)

        # Create stacks with placement injected
        stacks = []
        remaining = total_available

        for _ in range(number_of_stacks):  # type: ignore[arg-type]
            if remaining <= 0:
                break
            stack_count = min(count_per_stack, remaining)
            stacks.append(
                create_item_stack(
                    name=item_name,
                    count=stack_count,
                    placement=self._placement,
                    subgroup="raw-material",
                )
            )
            remaining -= stack_count

        return stacks

    # def check_recipe_count(self, recipe_name: str) -> int:
    #     """Check how many times a recipe can be crafted based on available ingredients.

    #     Args:
    #         recipe_name: Name of the recipe

    #     Returns:
    #         Maximum number of times the recipe can be crafted
    #     """
    #     recipe = self._factory.recipes[recipe_name]

    #     if not recipe or not recipe.ingredients:
    #         return 0

    #     # Calculate how many times we can craft for each ingredient
    #     max_crafts_per_ingredient = []
    #     for ingredient in recipe.ingredients:
    #         available_count = self.check_total(ingredient.name)
    #         if ingredient.count == 0:
    #             max_crafts_per_ingredient.append(float("inf"))
    #         else:
    #             max_crafts = available_count // ingredient.count
    #             max_crafts_per_ingredient.append(max_crafts)

    #     # Find the minimum (bottleneck ingredient)
    #     if not max_crafts_per_ingredient:
    #         return 0

    #     actual_crafts = min(max_crafts_per_ingredient)
    #     return int(actual_crafts) if actual_crafts != float("inf") else 0
