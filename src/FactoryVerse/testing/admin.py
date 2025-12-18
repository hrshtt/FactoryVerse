"""Admin API for testing FactoryVerse.

Provides high-level testing utilities that wrap both remote interface
calls (for agent-internal state) and RCON commands (for game-level operations).
"""

from typing import Dict, List, Any, Optional
from factorio_rcon import RCONClient
import json


class AdminAPI:
    """Admin API for testing FactoryVerse.
    
    Provides high-level testing utilities that wrap both remote interface
    calls (for agent-internal state) and RCON commands (for game-level operations).
    """
    
    def __init__(self, rcon: RCONClient, agent_id: int = 1):
        """Initialize admin API.
        
        Args:
            rcon: RCON client instance
            agent_id: Agent ID to operate on (default: 1)
        """
        self.rcon = rcon
        self.agent_id = agent_id
    
    def enable_admin_api(self):
        """Enable admin API via settings.
        
        Uses Factorio's ModSetting API to programmatically enable the admin interface.
        This triggers the on_runtime_mod_setting_changed event which re-registers the interface.
        """
        cmd = '/c settings.global["fv-embodied-agent-enable-admin-api"] = {value = true}'
        self.rcon.send_command(cmd)
    
    def disable_admin_api(self):
        """Disable admin API via settings.
        
        Uses Factorio's ModSetting API to programmatically disable the admin interface.
        This triggers the on_runtime_mod_setting_changed event which removes the interface.
        """
        cmd = '/c settings.global["fv-embodied-agent-enable-admin-api"] = {value = false}'
        self.rcon.send_command(cmd)
    
    # ========================================================================
    # Agent-Internal State (via remote interface)
    # ========================================================================
    
    def add_items(self, items: Dict[str, int]) -> Dict[str, Any]:
        """Add items to agent inventory.
        
        Args:
            items: Dict of {item_name: count}
            
        Returns:
            Result dict with items_added
        """
        items_json = json.dumps(items)
        cmd = f'/c local items = helpers.json_to_table(\'{items_json}\'); rcon.print(helpers.table_to_json(remote.call("admin", "add_items", {self.agent_id}, items)))'
        result = self.rcon.send_command(cmd)
        return json.loads(result)
    
    def clear_inventory(self) -> Dict[str, Any]:
        """Clear agent inventory."""
        cmd = f"/c rcon.print(helpers.table_to_json(remote.call('admin', 'clear_inventory', {self.agent_id})))"
        result = self.rcon.send_command(cmd)
        return json.loads(result)
    
    def unlock_technology(self, tech_name: str) -> Dict[str, Any]:
        """Unlock a technology for agent's force."""
        cmd = f"/c rcon.print(helpers.table_to_json(remote.call('admin', 'unlock_technology', {self.agent_id}, '{tech_name}')))"
        result = self.rcon.send_command(cmd)
        return json.loads(result)
    
    def set_crafting_speed(self, multiplier: float) -> Dict[str, Any]:
        """Set agent crafting speed multiplier."""
        cmd = f"/c rcon.print(helpers.table_to_json(remote.call('admin', 'set_crafting_speed', {self.agent_id}, {multiplier})))"
        result = self.rcon.send_command(cmd)
        return json.loads(result)
    
    def get_agent_state(self) -> Dict[str, Any]:
        """Get comprehensive agent state."""
        cmd = f"/c rcon.print(helpers.table_to_json(remote.call('admin', 'get_agent_state', {self.agent_id})))"
        result = self.rcon.send_command(cmd)
        return json.loads(result)
    
    # ========================================================================
    # Game-Level Operations (via RCON commands)
    # ========================================================================
    
    def set_game_speed(self, speed: float):
        """Set game speed multiplier."""
        self.rcon.send_command(f"/c game.speed = {speed}")
    
    def chart_area(self, x: float, y: float, radius: int = 100):
        """Chart an area around a position."""
        cmd = f"/c game.forces.player.chart(game.surfaces[1], {{{{{x-radius}, {y-radius}}}, {{{x+radius}, {y+radius}}}}})"
        self.rcon.send_command(cmd)
