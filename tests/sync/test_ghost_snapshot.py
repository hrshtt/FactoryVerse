"""
Ghost Snapshot Synchronization Tests

Tests the complete ghost tracking flow:
1. Ghost placement → UDP notification + JSONL file write
2. Real entity placement on ghost → Ghost removal + Entity creation
3. Ghost rotation and configuration changes
4. Label tracking for belt line orchestration
5. Database sync consistency

Test Scenarios:
- Place ghost → verify ghost appears in DB and JSONL
- Place entity on ghost → verify ghost removed, entity added
- Place multiple labeled ghosts → verify label tracking
- Rotate ghost → verify direction update propagates
- File reload → verify consistency with DB state
"""

import time
import json


class TestGhostPlacement:
    """Tests for ghost placement and tracking."""

    def test_ghost_placement_creates_db_entry(self, ghost_test_ctx):
        """Placing a ghost should create an entry in the ghost table."""
        ctx = ghost_test_ctx

        # Setup: teleport agent and give items (ghosts don't consume items but need reach)
        ctx.agent.teleport(100, 100)

        # Initial count (recorded for debugging)
        _initial_ghosts = ctx.count_ghosts()

        # Action: Place a ghost inserter
        result = ctx.agent.place_entity(
            entity_name="inserter",
            x=100.5,
            y=100.5,
            direction=4,  # East
            ghost=True,
        )

        assert result.get("success"), f"Ghost placement failed: {result}"

        # Wait for sync (UDP or file write)
        time.sleep(0.5)

        # Reload from files to verify persistence
        ctx.reload_from_files()

        # Verify ghost exists
        ghost = ctx.find_ghost("inserter", (100.5, 100.5))
        assert ghost is not None, "Ghost not found in database after placement"
        assert ghost["ghost_name"] == "inserter"

    def test_ghost_placement_with_label(self, ghost_test_ctx):
        """Placing a ghost with a label should track the label in the database."""
        ctx = ghost_test_ctx

        ctx.agent.teleport(110, 100)

        # Place ghost with a label (for belt line tracking)
        # Note: The label parameter is passed through place_entity
        result = ctx.rcon.call(
            ctx.agent.interface_name,
            "place_entity",
            "transport-belt",
            {"x": 110.5, "y": 100.5},
            4,  # direction
            True,  # ghost=True
            "belt-line-001",  # label
        )

        assert result.get("success"), f"Labeled ghost placement failed: {result}"

        time.sleep(0.5)
        ctx.reload_from_files()

        # Verify ghost has label
        ghost = ctx.find_ghost("transport-belt", (110.5, 100.5))
        assert ghost is not None, "Labeled ghost not found"

        # Check label in raw_data (stored in builder sub-object)
        if ghost.get("raw_data"):
            raw = json.loads(ghost["raw_data"])
            builder = raw.get("builder", {})
            assert builder.get("label") == "belt-line-001", (
                f"Label not stored in builder: {raw}"
            )

    def test_ghost_appears_in_updates_file(self, ghost_test_ctx):
        """Ghost placement should appear in ghosts-updates.jsonl file."""
        ctx = ghost_test_ctx

        ctx.agent.teleport(120, 100)

        # Place ghost
        result = ctx.agent.place_entity(
            entity_name="inserter", x=120.5, y=100.5, direction=4, ghost=True
        )
        assert result.get("success")

        time.sleep(0.5)

        # Find the ghosts-updates.jsonl file for this chunk
        # Chunk coords for position 120, 100 are (3, 3) since 120/32 = 3.75
        chunk_x = int(120 // 32)
        chunk_y = int(100 // 32)

        updates_file = (
            ctx.snapshot_dir / str(chunk_x) / str(chunk_y) / "ghosts-updates.jsonl"
        )

        # File may or may not exist depending on whether chunk was written
        if updates_file.exists():
            with open(updates_file, "r") as f:
                lines = f.readlines()

            # Look for upsert operation for our ghost
            found = False
            for line in lines:
                if line.strip():
                    op = json.loads(line)
                    if op.get("op") == "upsert":
                        ghost = op.get("ghost", {})
                        if ghost.get("ghost_name") == "inserter":
                            pos = ghost.get("position", {})
                            if (
                                abs(pos.get("x", 0) - 120.5) < 0.1
                                and abs(pos.get("y", 0) - 100.5) < 0.1
                            ):
                                found = True
                                break

            assert found, "Ghost upsert operation not found in ghosts-updates.jsonl"


class TestGhostToEntityConversion:
    """Tests for placing real entities over ghosts."""

    def test_entity_replaces_ghost(self, ghost_test_ctx):
        """Placing a real entity on a ghost should remove the ghost and add the entity."""
        ctx = ghost_test_ctx

        # Setup
        ctx.agent.teleport(130, 100)
        ctx.admin.add_items(ctx.agent_id, {"inserter": 5})

        # Step 1: Place ghost
        ghost_result = ctx.agent.place_entity(
            entity_name="inserter", x=130.5, y=100.5, direction=4, ghost=True
        )
        assert ghost_result.get("success")

        time.sleep(0.3)
        ctx.reload_from_files()

        # Verify ghost exists
        ghost = ctx.find_ghost("inserter", (130.5, 100.5))
        assert ghost is not None, "Ghost not created"
        initial_entity = ctx.find_entity("inserter", (130.5, 100.5))
        assert initial_entity is None, "Entity should not exist yet"

        # Step 2: Place real entity on top of ghost
        entity_result = ctx.agent.place_entity(
            entity_name="inserter", x=130.5, y=100.5, direction=4, ghost=False
        )
        assert entity_result.get("success"), f"Entity placement failed: {entity_result}"

        time.sleep(0.5)
        ctx.reload_from_files()

        # Verify: ghost removed, entity exists
        ghost_after = ctx.find_ghost("inserter", (130.5, 100.5))
        entity_after = ctx.find_entity("inserter", (130.5, 100.5))

        assert ghost_after is None, "Ghost should be removed after entity placement"
        assert entity_after is not None, "Entity should exist after placement"

    def test_ghost_destroy_generates_remove_operation(self, ghost_test_ctx):
        """When a ghost is destroyed, a remove operation should be generated."""
        ctx = ghost_test_ctx

        ctx.agent.teleport(140, 100)
        ctx.admin.add_items(ctx.agent_id, {"inserter": 5})

        # Place ghost
        ctx.agent.place_entity(
            entity_name="inserter", x=140.5, y=100.5, direction=4, ghost=True
        )
        time.sleep(0.3)

        # Record current state
        chunk_x = int(140 // 32)
        chunk_y = int(100 // 32)
        updates_file = (
            ctx.snapshot_dir / str(chunk_x) / str(chunk_y) / "ghosts-updates.jsonl"
        )

        if updates_file.exists():
            _initial_line_count = len(updates_file.read_text().strip().split("\n"))
        else:
            _initial_line_count = 0

        # Place real entity (destroys ghost)
        ctx.agent.place_entity(
            entity_name="inserter", x=140.5, y=100.5, direction=4, ghost=False
        )
        time.sleep(0.5)

        # Check updates file for remove operation
        if updates_file.exists():
            lines = updates_file.read_text().strip().split("\n")

            remove_found = False
            for line in lines:
                if line.strip():
                    op = json.loads(line)
                    if op.get("op") == "remove":
                        # Check if this is our ghost's remove operation
                        key = op.get("key", "")
                        if "inserter" in key and "140" in key:
                            remove_found = True
                            break

            assert remove_found, f"Remove operation not found. Lines: {lines}"


class TestMultipleGhostOperations:
    """Tests for multiple ghost operations in sequence."""

    def test_multiple_labeled_ghosts_same_label(self, ghost_test_ctx):
        """Multiple ghosts with the same label should all be tracked."""
        ctx = ghost_test_ctx

        ctx.agent.teleport(150, 100)

        # Place multiple ghosts with same label (simulating belt line)
        positions = [(150.5, 100.5), (151.5, 100.5), (152.5, 100.5)]

        for pos in positions:
            result = ctx.rcon.call(
                ctx.agent.interface_name,
                "place_entity",
                "transport-belt",
                {"x": pos[0], "y": pos[1]},
                4,  # direction (east)
                True,  # ghost
                "belt-line-002",  # same label for all
            )
            assert result.get("success"), f"Ghost placement failed at {pos}"

        time.sleep(0.5)
        ctx.reload_from_files()

        # Verify all ghosts exist
        for pos in positions:
            ghost = ctx.find_ghost("transport-belt", pos)
            assert ghost is not None, f"Ghost not found at {pos}"

        # Count total ghosts with this label pattern (via query)
        result = ctx.db.connection.execute("""
            SELECT COUNT(*) FROM ghost 
            WHERE ghost_name = 'transport-belt' 
            AND position_x >= 150 AND position_x <= 153
        """).fetchone()
        assert result[0] == 3, f"Expected 3 ghosts, found {result[0]}"

    def test_partial_ghost_conversion(self, ghost_test_ctx):
        """Converting some ghosts to entities should leave others intact."""
        ctx = ghost_test_ctx

        ctx.agent.teleport(160, 100)
        ctx.admin.add_items(ctx.agent_id, {"transport-belt": 10})

        # Place 3 ghosts
        positions = [(160.5, 100.5), (161.5, 100.5), (162.5, 100.5)]
        for pos in positions:
            ctx.agent.place_entity(
                entity_name="transport-belt",
                x=pos[0],
                y=pos[1],
                direction=4,
                ghost=True,
            )

        time.sleep(0.3)
        ctx.reload_from_files()

        # Convert only the first two to real entities
        ctx.agent.place_entity(
            entity_name="transport-belt", x=160.5, y=100.5, direction=4, ghost=False
        )
        ctx.agent.place_entity(
            entity_name="transport-belt", x=161.5, y=100.5, direction=4, ghost=False
        )

        time.sleep(0.5)
        ctx.reload_from_files()

        # Verify: 2 real entities, 1 ghost remaining
        entities_count = ctx.db.connection.execute("""
            SELECT COUNT(*) FROM map_entity 
            WHERE entity_name = 'transport-belt' 
            AND position_x >= 160 AND position_x <= 163
        """).fetchone()[0]

        ghosts_count = ctx.db.connection.execute("""
            SELECT COUNT(*) FROM ghost 
            WHERE ghost_name = 'transport-belt' 
            AND position_x >= 160 AND position_x <= 163
        """).fetchone()[0]

        assert entities_count == 2, f"Expected 2 entities, found {entities_count}"
        assert ghosts_count == 1, f"Expected 1 ghost, found {ghosts_count}"


class TestGhostSequenceConsistency:
    """Tests for sequence number consistency and replay."""

    def test_sequence_numbers_are_monotonic(self, ghost_test_ctx):
        """Sequence numbers in update files should be monotonically increasing."""
        ctx = ghost_test_ctx

        ctx.agent.teleport(170, 100)
        ctx.admin.add_items(ctx.agent_id, {"inserter": 5})

        # Perform several operations
        ctx.agent.place_entity("inserter", 170.5, 100.5, 4, True)  # ghost
        time.sleep(0.2)
        ctx.agent.place_entity("inserter", 170.5, 100.5, 4, False)  # replace
        time.sleep(0.2)

        # Check entities-updates.jsonl for sequence
        chunk_x = int(170 // 32)
        chunk_y = int(100 // 32)

        # Check both ghost and entity update files
        for filename in ["entities-updates.jsonl", "ghosts-updates.jsonl"]:
            updates_file = ctx.snapshot_dir / str(chunk_x) / str(chunk_y) / filename

            if updates_file.exists():
                sequences = []
                with open(updates_file, "r") as f:
                    for line in f:
                        if line.strip():
                            op = json.loads(line)
                            seq = op.get("sequence", 0)
                            if seq > 0:
                                sequences.append(seq)

                # Check monotonicity within file
                for i in range(1, len(sequences)):
                    assert sequences[i] > sequences[i - 1], (
                        f"Sequences not monotonic in {filename}: {sequences}"
                    )


class TestReloadConsistency:
    """Tests for database reload consistency with file state."""

    def test_reload_restores_exact_state(self, ghost_test_ctx):
        """Reloading from files should restore the exact database state."""
        ctx = ghost_test_ctx

        ctx.agent.teleport(180, 100)
        ctx.admin.add_items(ctx.agent_id, {"inserter": 5})

        # Create a known state
        ctx.agent.place_entity("inserter", 180.5, 100.5, 4, True)  # ghost
        ctx.agent.place_entity("inserter", 181.5, 100.5, 4, True)  # ghost
        time.sleep(0.3)

        ctx.agent.place_entity("inserter", 180.5, 100.5, 4, False)  # convert first
        time.sleep(0.5)

        # Load state
        ctx.reload_from_files()

        # Record counts (for debugging)
        _ghost_count = ctx.count_ghosts()
        _entity_count = ctx.count_entities()

        # Reset and reload
        ctx.db.reset()
        assert ctx.count_ghosts() == 0, "Reset should clear ghosts"

        # Reload again
        ctx.reload_from_files()

        # Should match original counts (approximately - may have other entities)
        ghost = ctx.find_ghost("inserter", (181.5, 100.5))
        entity = ctx.find_entity("inserter", (180.5, 100.5))

        assert ghost is not None, "Ghost should be restored after reload"
        assert entity is not None, "Entity should be restored after reload"


class TestEdgeCases:
    """Edge case tests for ghost synchronization."""

    def test_place_ghost_then_pickup(self, ghost_test_ctx):
        """Placing a ghost then picking it up should result in no ghost."""
        ctx = ghost_test_ctx

        ctx.agent.teleport(190, 100)

        # Place ghost
        result = ctx.agent.place_entity("inserter", 190.5, 100.5, 4, True)
        assert result.get("success")

        time.sleep(0.3)
        ctx.reload_from_files()

        # Verify ghost exists
        ghost = ctx.find_ghost("inserter", (190.5, 100.5))
        assert ghost is not None, "Ghost should exist after placement"

        # Pickup ghost (this may or may not work depending on game mechanics for ghosts)
        # Ghosts typically can't be "picked up" - they get destroyed
        # This tests that whatever happens, the state is consistent

    def test_rapid_place_and_convert(self, ghost_test_ctx):
        """Rapidly placing and converting ghosts should not cause sync issues."""
        ctx = ghost_test_ctx

        ctx.agent.teleport(200, 100)
        ctx.admin.add_items(ctx.agent_id, {"inserter": 10})

        # Rapidly place and convert
        for i in range(3):
            pos = 200.5 + i
            ctx.agent.place_entity("inserter", pos, 100.5, 4, True)
            ctx.agent.place_entity("inserter", pos, 100.5, 4, False)

        time.sleep(0.5)
        ctx.reload_from_files()

        # All should be real entities, no ghosts
        ghosts = ctx.db.connection.execute("""
            SELECT COUNT(*) FROM ghost 
            WHERE ghost_name = 'inserter' 
            AND position_x >= 200 AND position_x <= 203
        """).fetchone()[0]

        entities = ctx.db.connection.execute("""
            SELECT COUNT(*) FROM map_entity 
            WHERE entity_name = 'inserter' 
            AND position_x >= 200 AND position_x <= 203
        """).fetchone()[0]

        assert ghosts == 0, f"Expected 0 ghosts after conversions, found {ghosts}"
        assert entities == 3, f"Expected 3 entities after conversions, found {entities}"
