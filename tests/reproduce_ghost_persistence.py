
import logging
import shutil
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.FactoryVerse.dsl.agent import PlayingFactory
from src.FactoryVerse.dsl.ghosts import GhostManager
from src.FactoryVerse.dsl.types import MapPosition
from src.FactoryVerse.cli import cmd_client_launch, cmd_start
import argparse

# Configure logging to capture warnings
logging.basicConfig(level=logging.INFO)

class TestGhostPersistence(unittest.TestCase):
    def setUp(self):
        self.agent_id = "agent_test"
        self.output_dir = Path(".fv-output")
        self.agent_dir = self.output_dir / self.agent_id
        self.ghost_file = self.agent_dir / "ghosts.json"
        
        # Clean up before test
        if self.agent_dir.exists():
            shutil.rmtree(self.agent_dir)
        
        # Mock components
        self.rcon_mock = MagicMock()
        self.recipes_mock = MagicMock()
        self.udp_mock = MagicMock()
        
    def tearDown(self):
        # Clean up after test
        if self.agent_dir.exists():
            shutil.rmtree(self.agent_dir)

    def test_persistence_flow(self):
        print("\n--- Testing Persistence Flow ---")
        
        # 1. Initialize Factory and add ghost
        factory1 = PlayingFactory(self.rcon_mock, self.agent_id, self.recipes_mock, self.udp_mock)
        ghost_pos = MapPosition(x=10, y=10)
        
        # Mock place_entity rcon response
        self.rcon_mock.send_command.return_value = '{"success": true, "tick": 100}'
        
        factory1.place_entity("inserter", ghost_pos, ghost=True, label="test_label")
        
        # Verify file created
        self.assertTrue(self.ghost_file.exists(), "Ghost file should exist")
        print(f"✓ Ghost file created at {self.ghost_file}")
        
        # 2. Re-initialize Factory (simulate restart)
        factory2 = PlayingFactory(self.rcon_mock, self.agent_id, self.recipes_mock, self.udp_mock)
        
        # Verify ghost loaded
        ghosts = factory2.ghosts.get_ghosts(label="test_label")
        self.assertEqual(len(ghosts), 1, "Should have loaded 1 ghost")
        self.assertEqual(ghosts[0]["entity_name"], "inserter", "Entity name should match")
        print("✓ Ghost loaded from disk")

    def test_replacement_warning(self):
        print("\n--- Testing Replacement Warning ---")
        
        factory = PlayingFactory(self.rcon_mock, self.agent_id, self.recipes_mock, self.udp_mock)
        ghost_pos = MapPosition(x=20, y=20)
        
        # Add ghost directly
        factory.ghosts.add_ghost(ghost_pos, "assembler", label="setup")
        
        # Mock place_entity (real) success
        self.rcon_mock.send_command.return_value = '{"success": true, "tick": 200}'
        
        with self.assertLogs('src.FactoryVerse.dsl.agent', level='WARNING') as cm:
            factory.place_entity("assembler", ghost_pos, ghost=False)
            
            # Verify warning
            self.assertTrue(any("replaced by real entity" in o for o in cm.output))
            print("✓ Warning logged on replacement")
            
        # Verify removed from manager
        self.assertEqual(len(factory.ghosts.list_ghosts()), 0, "Ghost should be removed")
        print("✓ Ghost removed from manager")
        
    def test_cli_reset(self):
        print("\n--- Testing CLI Reset ---")
        
        # Create dummy ghost file
        self.agent_dir.mkdir(parents=True, exist_ok=True)
        self.ghost_file.write_text("{}")
        
        # Mock CLI args
        args = argparse.Namespace(
            reset_ghosts=True, 
            scenario="factorio_verse", 
            force=False, 
            watch=False,
            num=1,
            name=None
        )
        
        # Mock dependencies in cli execution to avoid real side effects
        with patch('src.FactoryVerse.cli.FactorioServerManager') as mock_mgr, \
             patch('src.FactoryVerse.cli.launch_factorio_client') as mock_launch, \
             patch('src.FactoryVerse.cli.setup_client'), \
             patch('src.FactoryVerse.cli.DockerComposeManager'), \
             patch('src.FactoryVerse.cli.JupyterManager'):
                 
            # Run client launch with reset
            cmd_client_launch(args)
            
            self.assertFalse(self.ghost_file.exists(), "Ghost file should be deleted")
            print("✓ Ghost file deleted by CLI")

if __name__ == '__main__':
    unittest.main()
