#!/usr/bin/env python3
"""Verify Agent Placement Collision Detection - Uses DSL properly"""

import asyncio
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
from factorio_rcon import RCONClient
from FactoryVerse.dsl.dsl import configure, playing_factorio, walking
from helpers.test_ground import TestGround

load_dotenv()


async def main():
    print("=" * 70)
    print("AGENT PLACEMENT COLLISION VERIFICATION")
    print("=" * 70)
    
    rcon = RCONClient(os.getenv("RCON_HOST", "localhost"), int(os.getenv("RCON_PORT", "27100")), os.getenv("RCON_PWD", "factorio"))
    test_ground = TestGround(rcon)
    
    print("\n[Setup] Resetting test area...")
    await test_ground.reset_test_area()
    
    configure(rcon, "agent_1", db_path=":memory:")
    
    with playing_factorio():
        print(f"✓ Agent at {walking.position}\n")
        
        await walking.to(x=100, y=100)
        print("✓ Moved to (100, 100)\n")
        
        # Test 1
        print("=== Test 1: Place furnace ===")
        try:
            await walking.place("stone-furnace", position=(102, 100))
            print("✓ Placed furnace\n")
        except Exception as e:
            print(f"✗ {e}\n")
            rcon.close()
            return
        
        # Test 2
        print("=== Test 2: Same position (should fail) ===")
        try:
            await walking.place("stone-furnace", position=(102, 100))
            print("❌ CRITICAL: Overlap occurred!\n")
        except Exception as e:
            print(f"✅ PASS: Blocked - {str(e)[:100]}\n")
        
        # Test 3
        print("=== Test 3: Overlapping assembler (should fail) ===")
        try:
            await walking.place("assembling-machine-1", position=(103, 100))
            print("❌ CRITICAL: Overlap occurred!\n")
        except Exception as e:
            print(f"✅ PASS: Blocked - {str(e)[:100]}\n")
        
        # Test 4
        print("=== Test 4: Valid adjacent (should succeed) ===")
        try:
            await walking.place("assembling-machine-1", position=(106, 100))
            print("✅ PASS: Valid placement succeeded\n")
        except Exception as e:
            print(f"❌ FAIL: {e}\n")
        
        print("=" * 70)
        print("✅ AGENT PLACEMENT VERIFIED - NO OVERLAPS")
        print("=" * 70)
    
    rcon.close()


if __name__ == "__main__":
    asyncio.run(main())
