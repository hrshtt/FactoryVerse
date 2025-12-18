import asyncio
import json
import logging
from unittest.mock import MagicMock
from FactoryVerse.dsl import dsl
from FactoryVerse.dsl.factoriopedia import Factoriopedia

# Mock RCON Client
class MockRcon:
    def send_command(self, command: str) -> str:
        print(f"RCON CMD: {command}")
        # Mock responses
        if "get_recipes" in command:
            return json.dumps({}) 
        if "inspect" in command:
            return json.dumps({"inventory": {"coal": 10}, "entities": []})
        if "walk_to" in command:
            return json.dumps({"queued": False, "action_id": "walk_123", "success": True})
        if "mine_resource" in command:
            # Revert to fast completion for basic test
            return json.dumps({"queued": False, "action_id": "mine_123", "success": True})
        if "craft_enqueue" in command:
            return json.dumps({"queued": False, "action_id": "craft_123", "success": True})
        return "{}"

async def main():
    logging.basicConfig(level=logging.INFO, format='%(name)s - %(levelname)s - %(message)s')
    print("=== Verifying Factoriopedia Integration ===")
    wiki = Factoriopedia()
    prompt = wiki.system_prompt()
    print("System Prompt snippet:", prompt.split('\n')[2])
    
    assert "factoriopedia.lookup_item" in prompt
    print("✅ Factoriopedia system prompt OK")
    
    print("\n=== Verifying DSL init_context (Standalone) ===")
    rcon = MockRcon()
    
    try:
        if hasattr(dsl, 'factoriopedia'):
            print("❌ DSL should not have factoriopedia exported!")
            exit(1)

        # Configure DSL once
        dsl.configure(rcon, "agent_1")
        
        # Agent usage
        with dsl.playing_factorio() as factory:
            print("Context initialized.")
            
            # Test DSL action
            res = await dsl.walking.to(dsl.MapPosition(10, 20), strict_goal=True)
            print("Walking result:", res)
            
            res_mining = await dsl.mining.mine("coal", max_count=5)
            print("Mining result:", res_mining)
            
            inv = factory.inventory.item_stacks
            print("Inventory:", inv)
            
            print("✅ DSL context usage OK")
            
    except Exception as e:
        print(f"❌ DSL Context failed: {e}")
        import traceback
        traceback.print_exc()
        raise

if __name__ == "__main__":
    asyncio.run(main())
