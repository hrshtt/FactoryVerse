#!/usr/bin/env python3
"""
Basic Snapshot Functionality Verification

Tests the most fundamental snapshot operations to ensure they work:
1. Connect to test-ground remote interface
2. Place a single entity
3. Force a snapshot
4. Check snapshot status
5. Verify snapshot files created

Run with: uv run python tests/verify_snapshot_basics.py
"""

import asyncio
import json
from pathlib import Path
from factorio_rcon import RCONClient


class SnapshotVerifier:
    """Simple verifier for basic snapshot operations."""
    
    def __init__(self, rcon_host="localhost", rcon_port=27100, rcon_password="factorio"):
        self.rcon = RCONClient(rcon_host, rcon_port, rcon_password)
        
    def send_command(self, cmd: str) -> str:
        """Send RCON command and return response."""
        return self.rcon.send_command(cmd)
    
    def call_remote(self, interface: str, method: str, *args) -> any:
        """Call a remote interface method."""
        # Build Lua arguments
        lua_args = ", ".join(self._to_lua(arg) for arg in args)
        
        # Build command
        cmd = f"/c local result = remote.call('{interface}', '{method}'{', ' + lua_args if lua_args else ''}); if type(result) == 'table' then rcon.print(helpers.table_to_json(result)) else rcon.print(tostring(result)) end"
        
        response = self.send_command(cmd)
        
        if not response:
            return None
            
        # Try to parse as JSON
        try:
            return json.loads(response)
        except:
            return response
    
    def _to_lua(self, value):
        """Convert Python value to Lua literal."""
        if isinstance(value, bool):
            return "true" if value else "false"
        elif isinstance(value, (int, float)):
            return str(value)
        elif isinstance(value, str):
            return f'"{value}"'
        elif isinstance(value, dict):
            items = [f'["{k}"] = {self._to_lua(v)}' for k, v in value.items()]
            return "{" + ", ".join(items) + "}"
        elif isinstance(value, list):
            items = [self._to_lua(v) for v in value]
            return "{" + ", ".join(items) + "}"
        elif value is None:
            return "nil"
        else:
            raise ValueError(f"Cannot convert {type(value)} to Lua")
    
    def verify_test_ground_interface(self):
        """Step 1: Verify test-ground interface is accessible."""
        print("\n=== Step 1: Verify test-ground interface ===")
        
        try:
            size = self.call_remote("test_ground", "get_test_area_size")
            print(f"✓ test-ground interface accessible")
            print(f"  Test area size: {size}")
            return True
        except Exception as e:
            print(f"✗ Failed to access test-ground interface: {e}")
            return False
    
    def verify_entity_placement(self):
        """Step 2: Place a single entity."""
        print("\n=== Step 2: Place test entity ===")
        
        try:
            # Reset test area first
            reset_result = self.call_remote("test_ground", "reset_test_area")
            print(f"✓ Test area reset: {reset_result.get('message', 'OK')}")
            
            # Place a stone furnace at origin
            result = self.call_remote(
                "test_ground", 
                "place_entity",
                "stone-furnace",
                {"x": 0, "y": 0},
                None,  # direction
                "player"  # force
            )
            
            if result and result.get("success"):
                print(f"✓ Entity placed successfully")
                print(f"  Entity: {result['metadata']['name']}")
                print(f"  Position: ({result['metadata']['position']['x']}, {result['metadata']['position']['y']})")
                print(f"  Entity ID: {result['metadata']['entity_id']}")
                return True
            else:
                print(f"✗ Entity placement failed: {result}")
                return False
                
        except Exception as e:
            print(f"✗ Entity placement error: {e}")
            return False
    
    def verify_snapshot_status_interface(self):
        """Step 3: Check snapshot status interface."""
        print("\n=== Step 3: Check snapshot status ===")
        
        try:
            status = self.call_remote("map", "get_snapshot_status")
            
            if status:
                print(f"✓ Snapshot status accessible")
                print(f"  Phase: {status.get('phase', 'UNKNOWN')}")
                print(f"  System phase: {status.get('system_phase', 'UNKNOWN')}")
                print(f"  Pending chunks: {status.get('pending_chunks', 'N/A')}")
                print(f"  Completed chunks: {status.get('completed_chunks', 'N/A')}")
                return True
            else:
                print(f"✗ Failed to get snapshot status")
                return False
                
        except Exception as e:
            print(f"✗ Snapshot status error: {e}")
            return False
    
    def verify_force_resnapshot(self):
        """Step 4: Force a resnapshot."""
        print("\n=== Step 4: Force resnapshot ===")
        
        try:
            # Force resnapshot of chunk (0, 0) which contains our entity at origin
            result = self.call_remote(
                "test_ground",
                "force_resnapshot",
                [{"x": 0, "y": 0}]
            )
            
            if result and result.get("success"):
                print(f"✓ Resnapshot triggered")
                print(f"  Chunks enqueued: {result.get('chunks_enqueued', 0)}")
                print(f"  Total chunks: {result.get('total_chunks', 0)}")
                return True
            else:
                print(f"✗ Resnapshot failed: {result}")
                return False
                
        except Exception as e:
            print(f"✗ Resnapshot error: {e}")
            return False
    
    def wait_for_snapshot_completion(self, timeout=10):
        """Step 5: Wait for snapshot to complete."""
        print("\n=== Step 5: Wait for snapshot completion ===")
        
        import time
        start = time.time()
        
        try:
            while time.time() - start < timeout:
                status = self.call_remote("map", "get_snapshot_status")
                
                if status:
                    phase = status.get("phase", "UNKNOWN")
                    pending = status.get("pending_chunks", 0)
                    
                    print(f"  Phase: {phase}, Pending: {pending}", end="\r")
                    
                    # Check if snapshot is complete (IDLE phase and no pending chunks)
                    if phase == "IDLE" and pending == 0:
                        print(f"\n✓ Snapshot completed")
                        print(f"  Completed chunks: {status.get('completed_chunks', 0)}")
                        return True
                
                time.sleep(0.5)
            
            print(f"\n✗ Snapshot did not complete within {timeout}s")
            return False
            
        except Exception as e:
            print(f"\n✗ Error waiting for snapshot: {e}")
            return False
    
    def verify_snapshot_files(self):
        """Step 6: Check if snapshot files were created."""
        print("\n=== Step 6: Verify snapshot files ===")
        
        # Get snapshot directory from config
        try:
            # Snapshot directory: script-output/factoryverse/snapshots/
            factorio_dir = Path.home() / "Library" / "Application Support" / "factorio"
            snapshot_dir = factorio_dir / "script-output" / "factoryverse" / "snapshots"
            
            print(f"  Looking for snapshots in: {snapshot_dir}")
            
            if not snapshot_dir.exists():
                print(f"✗ Snapshot directory does not exist: {snapshot_dir}")
                return False
            
            # Look for chunk (0,0) snapshots - structure is chunk_x/chunk_y/
            chunk_dir = snapshot_dir / "0" / "0"
            
            if not chunk_dir.exists():
                print(f"✗ Chunk directory does not exist: {chunk_dir}")
                
                # List what's actually there
                print(f"  Available in snapshot dir:")
                for item in snapshot_dir.iterdir():
                    print(f"    - {item.name}")
                return False
            
            print(f"✓ Chunk directory exists: {chunk_dir}")
            
            # Check for entities_init.jsonl
            entities_file = chunk_dir / "entities_init.jsonl"
            if entities_file.exists():
                print(f"✓ entities_init.jsonl found")
                
                # Read and display first line
                with open(entities_file) as f:
                    first_line = f.readline().strip()
                    if first_line:
                        entity_data = json.loads(first_line)
                        print(f"  Entity: {entity_data.get('name', 'unknown')}")
                        print(f"  Position: {entity_data.get('position', {})}")
                return True
            else:
                print(f"✗ entities_init.jsonl not found")
                print(f"  Available in chunk dir:")
                for item in chunk_dir.iterdir():
                    print(f"    - {item.name}")
                return False
                
        except Exception as e:
            print(f"✗ Error verifying snapshot files: {e}")
            return False
    
    def run_all_verifications(self):
        """Run all verification steps."""
        print("=" * 60)
        print("BASIC SNAPSHOT FUNCTIONALITY VERIFICATION")
        print("=" * 60)
        
        results = []
        
        # Step 1: Check interface
        results.append(("test-ground interface", self.verify_test_ground_interface()))
        
        if not results[-1][1]:
            print("\n❌ Cannot proceed without test-ground interface")
            return False
        
        # Step 2: Place entity
        results.append(("entity placement", self.verify_entity_placement()))
        
        # Step 3: Check status interface
        results.append(("snapshot status", self.verify_snapshot_status_interface()))
        
        # Step 4: Force resnapshot
        results.append(("force resnapshot", self.verify_force_resnapshot()))
        
        # Step 5: Wait for completion
        results.append(("snapshot completion", self.wait_for_snapshot_completion()))
        
        # Step 6: Verify files
        results.append(("snapshot files", self.verify_snapshot_files()))
        
        # Summary
        print("\n" + "=" * 60)
        print("VERIFICATION SUMMARY")
        print("=" * 60)
        
        for name, success in results:
            status = "✓ PASS" if success else "✗ FAIL"
            print(f"{status:8} {name}")
        
        all_passed = all(success for _, success in results)
        
        print("=" * 60)
        if all_passed:
            print("✅ ALL VERIFICATIONS PASSED")
            print("\nSnapshot system is working! Ready for comprehensive tests.")
        else:
            print("❌ SOME VERIFICATIONS FAILED")
            print("\nFix the failing components before proceeding with comprehensive tests.")
        print("=" * 60)
        
        return all_passed


def main():
    """Run basic snapshot verification."""
    verifier = SnapshotVerifier()
    
    try:
        success = verifier.run_all_verifications()
        return 0 if success else 1
    except KeyboardInterrupt:
        print("\n\nVerification interrupted by user")
        return 1
    except Exception as e:
        print(f"\n\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        verifier.rcon.close()


if __name__ == "__main__":
    exit(main())
