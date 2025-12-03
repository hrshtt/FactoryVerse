#!/usr/bin/env python3
"""
FactoryVerse CLI - File-based experiment tracking.

Manages Jupyter notebook server and multiple Factorio servers.
"""

import argparse
import sys
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any

from .infra.docker import DockerComposeManager, FactorioServerManager, JupyterManager, HotreloadWatcher
from .infra.factorio_client_setup import setup_client, launch_factorio_client, sync_hotreload_to_client, read_factorio_log, dump_data_raw


class SimpleExperimentTracker:
    """File-based experiment tracking."""
    
    def __init__(self, work_dir: Path):
        self.work_dir = work_dir
        self.experiments_file = work_dir / ".fv-output" / "experiments.json"
        self.experiments_file.parent.mkdir(parents=True, exist_ok=True)
        self.experiments: Dict[str, Any] = {}
        self._load()
    
    def _load(self):
        """Load experiments from file."""
        if self.experiments_file.exists():
            with open(self.experiments_file) as f:
                self.experiments = json.load(f)
    
    def _save(self):
        """Save experiments to file."""
        with open(self.experiments_file, 'w') as f:
            json.dump(self.experiments, f, indent=2, default=str)
    
    def list_experiments(self) -> List[Dict]:
        """List all experiments."""
        return list(self.experiments.values())
    
    def add_experiment(self, experiment_id: str, name: str, num_servers: int, scenario: str):
        """Add a new experiment."""
        self.experiments[experiment_id] = {
            "id": experiment_id,
            "name": name,
            "scenario": scenario,
            "num_servers": num_servers,
            "created_at": datetime.now().isoformat(),
            "status": "running"
        }
        self._save()
    
    def update_status(self, experiment_id: str, status: str):
        """Update experiment status."""
        if experiment_id in self.experiments:
            self.experiments[experiment_id]["status"] = status
            self._save()
    
    def get_experiment(self, experiment_id: str) -> Dict:
        """Get experiment by ID."""
        return self.experiments.get(experiment_id)


def cmd_client_launch(args):
    """Setup and launch Factorio client."""
    from pathlib import Path
    
    work_dir = Path.cwd()
    server_mgr = FactorioServerManager(work_dir)
    
    # Determine scenario
    scenario = args.scenario
    
    # Setup client
    if scenario == "factorio_verse":
        # Setup factorio_verse as scenario (no mod needed)
        print(f"📱 Setting up Factorio client (factorio_verse as SCENARIO)")
        setup_client(server_mgr.verse_mod_dir, scenario="factorio_verse", force=args.force,
                    project_scenarios_dir=server_mgr.scenarios_dir)
    else:
        # Setup factorio_verse as mod + specified scenario
        print(f"📱 Setting up Factorio client (factorio_verse as MOD, scenario: {scenario})")
        setup_client(server_mgr.verse_mod_dir, scenario=scenario, force=args.force, 
                    project_scenarios_dir=server_mgr.scenarios_dir)
    
    # Launch client
    print("\n🚀 Launching Factorio client...")
    launch_factorio_client()
    
    # Start hotreload watcher if requested (only for factorio_verse scenario mode)
    if args.watch and scenario != "factorio_verse":
        print("⚠️  --watch ignored: hotreload only works with scenario=factorio_verse")
    elif args.watch:
        print("\n🔥 Starting hot-reload watcher...")
        watcher = HotreloadWatcher(server_mgr.verse_mod_dir, debounce_ms=2000)  # 2 second debounce for IDE flush
        
        def sync_and_reload():
            sync_hotreload_to_client(server_mgr.verse_mod_dir)
        
        watcher.start(sync_and_reload)
        
        try:
            print("Press Ctrl+C to stop watching...")
            while True:
                import time
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping watcher...")
            watcher.stop()


def cmd_client_log(args):
    """Display Factorio client log file."""
    read_factorio_log(follow=args.follow)


def cmd_client_dump_data(args):
    """Dump Factorio data.raw to JSON."""
    from pathlib import Path
    work_dir = Path.cwd()
    server_mgr = FactorioServerManager(work_dir)
    dump_data_raw(server_mgr.verse_mod_dir, scenario=args.scenario, force=args.force, 
                  project_scenarios_dir=server_mgr.scenarios_dir)


def cmd_start(args):
    """Start Factorio servers with Jupyter AND setup client."""
    from pathlib import Path
    
    work_dir = Path.cwd()
    
    # Setup client first
    server_mgr = FactorioServerManager(work_dir)
    print(f"📱 Setting up Factorio client (scenario: {args.scenario})")
    setup_client(server_mgr.verse_mod_dir, scenario=args.scenario, force=args.force, project_scenarios_dir=server_mgr.scenarios_dir)
    
    # Clear server snapshot directories before starting
    print(f"🧹 Clearing server snapshot directories...")
    server_mgr.clear_all_server_snapshot_dirs(args.num)
    
    # Prepare server mods
    print(f"🚀 Starting FactoryVerse ({args.num} server(s), scenario: {args.scenario})")
    server_mgr.prepare_mods(args.scenario)
    
    # Build compose file with services from both managers
    compose_mgr = DockerComposeManager(work_dir)
    jupyter_mgr = JupyterManager(work_dir)
    
    compose_mgr.add_services("jupyter", jupyter_mgr.get_services())
    compose_mgr.add_services("factorio", server_mgr.get_services(args.num, args.scenario))
    compose_mgr.write_compose()
    compose_mgr.up()
    
    # Print server info
    for i in range(args.num):
        print(f"  Server {i}: localhost:{34197 + i}")
    print(f"📓 Jupyter: http://localhost:8888")
    
    # Track experiment
    if args.name:
        tracker = SimpleExperimentTracker(work_dir)
        experiment_id = f"exp_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        tracker.add_experiment(experiment_id, args.name, args.num, args.scenario)
        print(f"📝 Experiment '{args.name}' tracked (ID: {experiment_id})")
    
    # Start hotreload watcher if requested
    if args.watch:
        print("\n🔥 Starting hot-reload watcher...")
        watcher = HotreloadWatcher(server_mgr.verse_mod_dir, debounce_ms=2000)  # 2 second debounce for IDE flush
        
        def sync_and_reload():
            # Sync to all running servers
            for i in range(args.num):
                server_mgr.sync_hotreload_to_server(compose_mgr, server_id=i)
        
        watcher.start(sync_and_reload)
        
        try:
            print("Press Ctrl+C to stop watching...")
            while True:
                import time
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping watcher...")
            watcher.stop()


def cmd_stop(args):
    """Stop all services."""
    from pathlib import Path
    compose_mgr = DockerComposeManager(Path.cwd())
    compose_mgr.down()
    print("✅ Services stopped")


def cmd_restart(args):
    """Restart all services."""
    from pathlib import Path
    compose_mgr = DockerComposeManager(Path.cwd())
    compose_mgr.restart()
    print("✅ Services restarted")


def cmd_list(args):
    """List experiments."""
    from pathlib import Path
    work_dir = Path.cwd()
    tracker = SimpleExperimentTracker(work_dir)
    
    experiments = tracker.list_experiments()
    if not experiments:
        print("No experiments found.")
        return
    
    print(f"Experiments ({len(experiments)}):")
    print(f"{'ID':<20} {'Name':<20} {'Servers':<8} {'Scenario':<15} {'Status':<10} {'Created'}")
    print("-" * 100)
    for exp in experiments:
        created = datetime.fromisoformat(exp['created_at']).strftime('%Y-%m-%d %H:%M')
        print(f"{exp['id']:<20} {exp['name']:<20} {exp['num_servers']:<8} {exp['scenario']:<15} {exp['status']:<10} {created}")


def cmd_logs(args):
    """Show logs for a service."""
    from pathlib import Path
    compose_mgr = DockerComposeManager(Path.cwd())
    compose_mgr.logs(args.service, follow=args.follow)


def cmd_server(args):
    """Control individual servers."""
    from pathlib import Path
    compose_mgr = DockerComposeManager(Path.cwd())
    service_name = f"factorio_{args.server_id}"
    
    if args.action == "start":
        compose_mgr.start_service(service_name)
    elif args.action == "stop":
        compose_mgr.stop_service(service_name)
    elif args.action == "restart":
        compose_mgr.restart_service(service_name)


def main():
    parser = argparse.ArgumentParser(
        description="FactoryVerse: Run multiple Factorio servers with Jupyter",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command")
    
    # ========== CLIENT COMMAND ==========
    client_parser = subparsers.add_parser("client", help="Factorio client operations")
    client_subparsers = client_parser.add_subparsers(dest="client_action", help="Client action")
    
    # Client launch subcommand
    client_launch_parser = client_subparsers.add_parser("launch", help="Setup and launch Factorio client")
    client_launch_parser.add_argument("-s", "--scenario", default="factorio_verse", 
                                      help="Scenario to load (default: factorio_verse). Use 'test_scenario' for testing.")
    client_launch_parser.add_argument("-f", "--force", action="store_true", help="Force re-setup of client")
    client_launch_parser.add_argument("-w", "--watch", action="store_true", help="Enable hot-reload watcher (scenario mode only)")
    client_launch_parser.set_defaults(func=cmd_client_launch)
    
    # Client log subcommand
    client_log_parser = client_subparsers.add_parser("log", help="Display Factorio client log file")
    client_log_parser.add_argument("-f", "--follow", action="store_true", help="Follow log file (like tail -f)")
    client_log_parser.set_defaults(func=cmd_client_log)
    
    # Client dump-data subcommand
    client_dump_parser = client_subparsers.add_parser("dump-data", help="Dump Factorio data.raw to JSON")
    client_dump_parser.add_argument("-s", "--scenario", default="factorio_verse", help="Scenario to use (default: factorio_verse)")
    client_dump_parser.add_argument("-f", "--force", action="store_true", help="Force re-setup of client")
    client_dump_parser.set_defaults(func=cmd_client_dump_data)
    
    # ========== SERVER COMMAND ==========
    server_parser = subparsers.add_parser("server", help="Factorio server operations")
    server_subparsers = server_parser.add_subparsers(dest="server_action", help="Server action")
    
    # Server start subcommand
    server_start_parser = server_subparsers.add_parser("start", help="Setup client and start servers")
    server_start_parser.add_argument("-n", "--num", type=int, default=1, help="Number of servers (default: 1)")
    server_start_parser.add_argument("-s", "--scenario", default="test_scenario", help="Scenario to load (default: test_scenario)")
    server_start_parser.add_argument("--name", help="Experiment name (optional)")
    server_start_parser.add_argument("-f", "--force", action="store_true", help="Force re-setup of client")
    server_start_parser.add_argument("-w", "--watch", action="store_true", help="Enable hot-reload watcher")
    server_start_parser.set_defaults(func=cmd_start)
    
    # Server stop subcommand
    server_stop_parser = server_subparsers.add_parser("stop", help="Stop all services")
    server_stop_parser.set_defaults(func=cmd_stop)
    
    # Server restart subcommand
    server_restart_parser = server_subparsers.add_parser("restart", help="Restart all services")
    server_restart_parser.set_defaults(func=cmd_restart)
    
    # Server list subcommand
    server_list_parser = server_subparsers.add_parser("list", help="List experiments")
    server_list_parser.set_defaults(func=cmd_list)
    
    # Server logs subcommand
    server_logs_parser = server_subparsers.add_parser("logs", help="View logs")
    server_logs_parser.add_argument("service", help="Service name (e.g., factorio_0, jupyter)")
    server_logs_parser.add_argument("-f", "--follow", action="store_true", help="Follow logs")
    server_logs_parser.set_defaults(func=cmd_logs)
    
    # Server instance control subcommand
    server_instance_parser = server_subparsers.add_parser("instance", help="Control individual server instances")
    server_instance_parser.add_argument("action", choices=["start", "stop", "restart"], help="Action")
    server_instance_parser.add_argument("server_id", type=int, help="Server ID")
    server_instance_parser.set_defaults(func=cmd_server)
    
    args = parser.parse_args()
    
    if not hasattr(args, 'func'):
        parser.print_help()
        sys.exit(1)
    
    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
