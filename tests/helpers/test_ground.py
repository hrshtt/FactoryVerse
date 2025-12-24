"""
Test Ground Helper - Python interface to test-ground scenario

Provides high-level helpers for:
- Resource placement (patches, circles)
- Entity placement (single, grids)
- Area management (clear, reset)
- Snapshot control (force re-snapshot)
- Metadata validation

Usage:
    from tests.helpers.test_ground import TestGround
    
    tg = TestGround(rcon_client)
    
    # Place resources
    tg.place_iron_patch(x=64, y=-64, size=32, amount=10000)
    
    # Place entities
    tg.place_entity("stone-furnace", x=0, y=0)
    
    # Force re-snapshot
    tg.force_resnapshot()
    
    # Validate
    assert tg.validate_resource_at("iron-ore", x=64, y=-64)
"""

from typing import Dict, List, Tuple, Optional, Any
import json


class TestGround:
    """Helper class for interacting with test-ground scenario."""
    
    def __init__(self, rcon_client):
        """
        Initialize TestGround helper.
        
        Args:
            rcon_client: RCON client instance for sending commands
        """
        self.rcon = rcon_client
        
    async def __aenter__(self):
        """Async context manager entry."""
        await self._check_scenario()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        pass
    
    async def _check_scenario(self):
        """Verify that test-ground scenario is loaded."""
        result = await self._call_remote("test_ground", "get_test_area_size")
        if result is None:
            raise RuntimeError(
                "test-ground scenario not loaded. "
                "Make sure Factorio is running with the test-ground scenario."
            )
    
    async def _call_remote(self, interface: str, method: str, *args) -> Any:
        """
        Call a remote interface method.
        
        Args:
            interface: Remote interface name
            method: Method name
            *args: Method arguments
            
        Returns:
            Parsed result or None if error
        """
        # Build Lua arguments
        lua_args = ", ".join(self._to_lua(arg) for arg in args)
        
        # Build command - try with table_to_json first for tables
        cmd = f"/c local result = remote.call('{interface}', '{method}'{', ' + lua_args if lua_args else ''}); if type(result) == 'table' then rcon.print(helpers.table_to_json(result)) else rcon.print(result) end"
        
        # Execute
        response = self.rcon.send_command(cmd)
        
        if response is None or response == '':
            return None
            
        # Try to parse as JSON first (for tables)
        try:
            return json.loads(response)
        except (json.JSONDecodeError, TypeError):
            # If not JSON, try to parse as primitive value
            try:
                # Try as number
                if '.' in response:
                    return float(response)
                else:
                    return int(response)
            except ValueError:
                # Return as string
                return response
    
    def _to_lua(self, value: Any) -> str:
        """Convert Python value to Lua literal."""
        if isinstance(value, bool):
            return "true" if value else "false"
        elif isinstance(value, (int, float)):
            return str(value)
        elif isinstance(value, str):
            return f'"{value}"'
        elif isinstance(value, dict):
            # Lua tables use ["key"] = value syntax for string keys
            items = [f'["{k}"] = {self._to_lua(v)}' for k, v in value.items()]
            return "{" + ", ".join(items) + "}"
        elif isinstance(value, (list, tuple)):
            items = [self._to_lua(v) for v in value]
            return "{" + ", ".join(items) + "}"
        elif value is None:
            return "nil"
        else:
            raise ValueError(f"Cannot convert {type(value)} to Lua")
    
    # ========================================================================
    # RESOURCE PLACEMENT
    # ========================================================================
    
    # ========================================================================
    # RESOURCE PLACEMENT
    # ========================================================================
    
    async def place_resource_patch(
        self,
        resource_name: str,
        center_x: int,
        center_y: int,
        size: int,
        amount: int = 10000
    ) -> Dict[str, Any]:
        """Place a square resource patch."""
        return await self._call_remote(
            "test_ground",
            "place_resource_patch",
            resource_name,
            center_x,
            center_y,
            size,
            amount
        )
    
    async def place_iron_patch(self, x: int, y: int, size: int = 32, amount: int = 10000):
        """Convenience method for placing iron ore patch."""
        return await self.place_resource_patch("iron-ore", x, y, size, amount)
    
    async def place_copper_patch(self, x: int, y: int, size: int = 32, amount: int = 10000):
        """Convenience method for placing copper ore patch."""
        return await self.place_resource_patch("copper-ore", x, y, size, amount)
    
    async def place_coal_patch(self, x: int, y: int, size: int = 32, amount: int = 10000):
        """Convenience method for placing coal patch."""
        return await self.place_resource_patch("coal", x, y, size, amount)
    
    async def place_stone_patch(self, x: int, y: int, size: int = 32, amount: int = 10000):
        """Convenience method for placing stone patch."""
        return await self.place_resource_patch("stone", x, y, size, amount)
    
    async def place_resource_patch_circle(
        self,
        resource_name: str,
        center_x: int,
        center_y: int,
        radius: int,
        amount: int = 10000
    ) -> Dict[str, Any]:
        """Place a circular resource patch."""
        return await self._call_remote(
            "test_ground",
            "place_resource_patch_circle",
            resource_name,
            center_x,
            center_y,
            radius,
            amount
        )
    
    # ========================================================================
    # ENTITY PLACEMENT
    # ========================================================================
    
    async def place_entity(
        self,
        entity_name: str,
        x: float,
        y: float,
        direction: Optional[int] = None,
        force: str = "player"
    ) -> Dict[str, Any]:
        """Place an entity at a position."""
        return await self._call_remote(
            "test_ground",
            "place_entity",
            entity_name,
            {"x": x, "y": y},
            direction,
            force
        )
    
    async def place_entity_grid(
        self,
        entity_name: str,
        start_x: float,
        start_y: float,
        rows: int,
        cols: int,
        spacing_x: float = 2.0,
        spacing_y: float = 2.0
    ) -> Dict[str, Any]:
        """Place entities in a grid pattern."""
        return await self._call_remote(
            "test_ground",
            "place_entity_grid",
            entity_name,
            start_x,
            start_y,
            rows,
            cols,
            spacing_x,
            spacing_y
        )
    
    # ========================================================================
    # AREA MANAGEMENT
    # ========================================================================
    
    async def clear_area(
        self,
        left_top_x: int,
        left_top_y: int,
        right_bottom_x: int,
        right_bottom_y: int,
        preserve_characters: bool = True
    ) -> Dict[str, Any]:
        """Clear all entities in a bounding box."""
        bounds = {
            "left_top": {"x": left_top_x, "y": left_top_y},
            "right_bottom": {"x": right_bottom_x, "y": right_bottom_y}
        }
        return await self._call_remote(
            "test_ground",
            "clear_area",
            bounds,
            preserve_characters
        )
    
    async def reset_test_area(self) -> Dict[str, Any]:
        """Reset entire test area to clean state."""
        return await self._call_remote("test_ground", "reset_test_area")
    
    # ========================================================================
    # SNAPSHOT CONTROL
    # ========================================================================
    
    async def force_resnapshot(self, chunk_coords: Optional[List[Tuple[int, int]]] = None) -> Dict[str, Any]:
        """Force re-snapshot of specified chunks."""
        if chunk_coords is not None:
            lua_chunks = [{"x": x, "y": y} for x, y in chunk_coords]
        else:
            lua_chunks = None
        
        return await self._call_remote("test_ground", "force_resnapshot", lua_chunks)
    
    # ========================================================================
    # METADATA & VALIDATION
    # ========================================================================
    
    async def get_test_metadata(self) -> Dict[str, Any]:
        """Get test scenario metadata."""
        return await self._call_remote("test_ground", "get_test_metadata")
    
    async def validate_resource_at(
        self,
        resource_name: str,
        x: float,
        y: float,
        timeout: float = 2.0
    ) -> bool:
        """Validate that a resource exists at a position."""
        import asyncio
        import time
        start = time.time()
        
        while time.time() - start < timeout:
            result = await self._call_remote(
                "test_ground",
                "validate_resource_at",
                resource_name,
                {"x": x, "y": y}
            )
            
            if result and result.get("valid", False):
                return True
            
            # Wait a bit before retrying
            await asyncio.sleep(0.05)
        
        return False
    
    async def validate_entity_at(
        self,
        entity_name: str,
        x: float,
        y: float,
        timeout: float = 2.0
    ) -> bool:
        """Validate that an entity exists at a position."""
        import asyncio
        import time
        start = time.time()
        
        while time.time() - start < timeout:
            result = await self._call_remote(
                "test_ground",
                "validate_entity_at",
                entity_name,
                {"x": x, "y": y}
            )
            
            if result and result.get("valid", False):
                return True
            
            # Wait a bit before retrying
            await asyncio.sleep(0.05)
        
        return False
    
    async def get_test_bounds(self) -> Dict[str, Any]:
        """Get test area bounds."""
        return await self._call_remote("test_ground", "get_test_bounds")
    
    async def get_test_area_size(self) -> int:
        """Get test area size (512)."""
        return await self._call_remote("test_ground", "get_test_area_size")
