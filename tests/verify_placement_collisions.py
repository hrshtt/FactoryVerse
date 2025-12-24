#!/usr/bin/env python3
"""
Comprehensive Placement Collision Verification

Tests that the test-ground placement API prevents overlaps:
1. Same position placement (should fail second attempt)
2. Overlapping placement (should fail)
3. Adjacent placement (should succeed)
4. Various entity sizes (1x1, 2x2, 3x3)

Uses ONLY test_ground.place_entity() remote API - NO direct RCON.
"""

import asyncio
from factorio_rcon import RCONClient
from helpers.test_ground import TestGround



async def test_placement_collisions():
    """Verify placement system prevents overlaps."""
    
    print("=" * 70)
    print("PLACEMENT COLLISION PREVENTION VERIFICATION")
    print("=" * 70)
    
    # Initialize
    rcon = RCONClient("localhost", 27100, "factorio")
    test_ground = TestGround(rcon)
    
    # Reset test area
    print("\n[Setup] Resetting test area...")
    await test_ground.reset_test_area()
    print("✓ Test area clean")
    
    # Test 1: Same position - should fail second placement
    print("\n" + "=" * 70)
    print("TEST 1: Same Position (2x2 furnace)")
    print("=" * 70)
    
    result1 = await test_ground.place_entity("stone-furnace", x=10, y=10)
    print(f"First placement at (10, 10): {result1.get('success', False)}")
    if result1.get('success'):
        print(f"  Entity ID: {result1['metadata']['entity_id']}")
    
    result2 = await test_ground.place_entity("stone-furnace", x=10, y=10)
    print(f"Second placement at (10, 10): {result2.get('success', False)}")
    
    if result1.get('success') and not result2.get('success'):
        print("✅ PASS: Cannot place at same position")
    elif not result1.get('success'):
        print("❌ FAIL: First placement failed unexpectedly")
    elif result2.get('success'):
        print("❌ FAIL: Second placement succeeded - OVERLAP OCCURRED!")
    
    # Test 2: Overlapping placement (3x3 assemblers)
    print("\n" + "=" * 70)
    print("TEST 2: Overlapping (3x3 assemblers)")
    print("=" * 70)
    
    # Assembling-machine-1 is 3x3, centered on position
    # Placing at (20, 20) occupies tiles from 18.5-21.5, 18.5-21.5
    result1 = await test_ground.place_entity("assembling-machine-1", x=20, y=20)
    print(f"First assembler at (20, 20): {result1.get('success', False)}")
    if result1.get('success'):
        print(f"  Entity ID: {result1['metadata']['entity_id']}")
        print(f"  Occupies approximately: (18.5-21.5, 18.5-21.5)")
    
    # Try to place 2 tiles away - this SHOULD overlap with first
    # At (22, 20), would occupy 20.5-23.5, 18.5-21.5
    result2 = await test_ground.place_entity("assembling-machine-1", x=22, y=20)
    print(f"Second assembler at (22, 20) [2 tiles away]: {result2.get('success', False)}")
    
    if result1.get('success') and not result2.get('success'):
        print("✅ PASS: Overlapping placement prevented")
    elif not result1.get('success'):
        print("❌ FAIL: First placement failed unexpectedly")
    elif result2.get('success'):
        print("❌ FAIL: Overlapping placement succeeded - CRITICAL BUG!")
        print("  This would create overlapping assemblers!")
    
    # Test 3: Adjacent valid placement (3x3 assemblers)
    print("\n" + "=" * 70)
    print("TEST 3: Adjacent Valid Placement (3x3 assemblers)")
    print("=" * 70)
    
    # First at (30, 30) occupies 28.5-31.5, 28.5-31.5
    result1 = await test_ground.place_entity("assembling-machine-1", x=30, y=30)
    print(f"First assembler at (30, 30): {result1.get('success', False)}")
    
    # Place 4 tiles away (minimum valid spacing for 3x3)
    # At (34, 30), would occupy 32.5-35.5, 28.5-31.5 - no overlap
    result2 = await test_ground.place_entity("assembling-machine-1", x=34, y=30)
    print(f"Second assembler at (34, 30) [4 tiles away]: {result2.get('success', False)}")
    
    if result1.get('success') and result2.get('success'):
        print("✅ PASS: Valid adjacent placement succeeded")
    else:
        print("❌ FAIL: Valid placement was blocked")
    
    # Test 4: Small entities (1x1 inserters)
    print("\n" + "=" * 70)
    print("TEST 4: Small Entities (1x1 inserters)")
    print("=" * 70)
    
    result1 = await test_ground.place_entity("inserter", x=40, y=40)
    print(f"First inserter at (40, 40): {result1.get('success', False)}")
    
    # Try same position
    result2 = await test_ground.place_entity("inserter", x=40, y=40)
    print(f"Second inserter at (40, 40) [same]: {result2.get('success', False)}")
    
    # Try adjacent (1 tile away should succeed for 1x1)
    result3 = await test_ground.place_entity("inserter", x=41, y=40)
    print(f"Third inserter at (41, 40) [1 tile away]: {result3.get('success', False)}")
    
    if not result2.get('success') and result3.get('success'):
        print("✅ PASS: 1x1 collision detection working")
    else:
        print("❌ FAIL: 1x1 collision detection issue")
    
    # Test 5: Mixed sizes
    print("\n" + "=" * 70)
    print("TEST 5: Mixed Sizes (2x2 furnace + 1x1 inserter)")
    print("=" * 70)
    
    # Place 2x2 furnace at (50, 50) - occupies 49-51, 49-51
    result1 = await test_ground.place_entity("stone-furnace", x=50, y=50)
    print(f"Furnace at (50, 50): {result1.get('success', False)}")
    
    # Try to place inserter on top of furnace
    result2 = await test_ground.place_entity("inserter", x=50, y=50)
    print(f"Inserter at (50, 50) [on furnace]: {result2.get('success', False)}")
    
    # Try inserter adjacent to furnace edge
    result3 = await test_ground.place_entity("inserter", x=52, y=50)
    print(f"Inserter at (52, 50) [next to furnace]: {result3.get('success', False)}")
    
    if not result2.get('success') and result3.get('success'):
        print("✅ PASS: Mixed size collision detection working")
    else:
        print("❌ FAIL: Mixed size collision issue")
    
    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print("\nAll tests use test_ground.place_entity() remote API.")
    print("If any test shows overlaps occurring, it's a critical bug.")
    print("If all overlaps are prevented, the system is working correctly.")
    print("=" * 70)
    
    rcon.close()


if __name__ == "__main__":
    asyncio.run(test_placement_collisions())
