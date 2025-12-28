#!/usr/bin/env python3
"""
FactoryVerse CLI - Manage Factorio instances and experiment tracking.

Manages Jupyter notebook server, multiple Factorio servers, and data pipelines.
FactoryVerse mods (fv_embodied_agent + fv_snapshot) are ALWAYS loaded.
"""

import argparse
import sys
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any

from .config import get_config
from .infra.docker import (
    DockerComposeManager,
    FactorioServerManager,
    JupyterManager,
    HotreloadWatcher,
)
from .infra.factorio_client_setup import (
    setup_client,
    launch_factorio_client,
    sync_hotreload_to_client,
    read_factorio_log,
    dump_data_raw,
)
from .infra.data_dump import (
    refresh_data_dump,
    prune_data_raw,
    get_data_raw_path,
)
from .infra.instance_manager import (
    FactorioInstanceManager,
    NoInstanceError,
    MultipleInstancesError,
)


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
        with open(self.experiments_file, "w") as f:
            json.dump(self.experiments, f, indent=2, default=str)

    def list_experiments(self) -> List[Dict]:
        """List all experiments."""
        return list(self.experiments.values())

    def add_experiment(
        self, experiment_id: str, name: str, num_servers: int, scenario: str
    ):
        """Add a new experiment."""
        self.experiments[experiment_id] = {
            "id": experiment_id,
            "name": name,
            "scenario": scenario,
            "num_servers": num_servers,
            "created_at": datetime.now().isoformat(),
            "status": "running",
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
    """Setup and launch Factorio client with FactoryVerse mods."""
    config = get_config()
    work_dir = config.project_root

    scenario = args.scenario

    # Validate --watch only works with repo scenarios
    if args.watch and not config.is_repo_scenario(scenario):
        print(
            f"❌ Error: Cannot hot-reload scenario '{scenario}' - it's a local scenario.",
            file=sys.stderr,
        )
        print(
            "   Only repo scenarios (in src/factorio/scenarios/) can be hot-reloaded.",
            file=sys.stderr,
        )
        print(
            f"   Copy it to {config.scenarios_dir}/ first, or use without --watch.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Handle ghost reset
    if args.reset_ghosts:
        print("🧹 Clearing ghost state...")
        fv_output = config.fv_output_dir
        if fv_output.exists():
            for ghost_file in fv_output.glob("*/ghosts.json"):
                try:
                    ghost_file.unlink()
                    print(f"   Deleted {ghost_file}")
                except Exception as e:
                    print(f"   Failed to delete {ghost_file}: {e}")
            print("✓ Ghost state cleared")

    server_mgr = FactorioServerManager(work_dir, config)

    # Setup client (always with mods)
    print(f"📱 Setting up Factorio client (scenario: {scenario})")
    setup_client(
        work_dir,
        scenario=scenario,
        force=args.force,
        project_scenarios_dir=server_mgr.scenarios_dir,
    )

    # Launch client
    print("\n🚀 Launching Factorio client...")
    launch_factorio_client()

    # Start hotreload watcher if requested (only for repo scenarios)
    if args.watch:
        print("\n🔥 Starting hot-reload watcher for scenario files...")
        scenario_dir = config.scenarios_dir / scenario
        watcher = HotreloadWatcher(scenario_dir, debounce_ms=2000)

        def sync_and_reload():
            sync_hotreload_to_client(scenario_dir)

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
    config = get_config()
    work_dir = config.project_root
    server_mgr = FactorioServerManager(work_dir, config)

    dump_data_raw(
        work_dir,
        scenario=args.scenario,
        force=args.force,
        project_scenarios_dir=server_mgr.scenarios_dir,
    )


def cmd_start(args):
    """Start Factorio servers with Jupyter AND setup client."""
    config = get_config()
    work_dir = config.project_root

    scenario = args.scenario

    # Validate --watch only works with repo scenarios
    if args.watch and not config.is_repo_scenario(scenario):
        print(
            f"❌ Error: Cannot hot-reload scenario '{scenario}' - it's a local scenario.",
            file=sys.stderr,
        )
        print(
            "   Only repo scenarios (in src/factorio/scenarios/) can be hot-reloaded.",
            file=sys.stderr,
        )
        print(
            f"   Copy it to {config.scenarios_dir}/ first, or use without --watch.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Handle ghost reset
    if args.reset_ghosts:
        print("🧹 Clearing ghost state...")
        fv_output = config.fv_output_dir
        if fv_output.exists():
            for ghost_file in fv_output.glob("*/ghosts.json"):
                try:
                    ghost_file.unlink()
                    print(f"   Deleted {ghost_file}")
                except Exception as e:
                    print(f"   Failed to delete {ghost_file}: {e}")
            print("✓ Ghost state cleared")

    server_mgr = FactorioServerManager(work_dir, config)

    # Validate scenario exists
    if not server_mgr.validate_scenario(scenario):
        print(f"❌ Error: Scenario '{scenario}' not found.", file=sys.stderr)
        available = server_mgr.list_scenarios()
        if available:
            print(f"   Available scenarios: {', '.join(available)}", file=sys.stderr)
            print(
                "   Use 'uv run fv server list-scenarios' to see all available scenarios.",
                file=sys.stderr,
            )
        sys.exit(1)

    # Setup client (always with mods)
    print(f"📱 Setting up Factorio client (scenario: {scenario})")
    setup_client(
        work_dir,
        scenario=scenario,
        force=args.force,
        project_scenarios_dir=server_mgr.scenarios_dir,
    )

    # Clear server snapshot directories before starting
    print("🧹 Clearing server snapshot directories...")
    server_mgr.clear_all_server_snapshot_dirs(args.num)

    # Consolidate local scenarios to repo (for Docker access)
    server_mgr.consolidate_scenarios()

    # Prepare server mods (always)
    print(f"🚀 Starting FactoryVerse ({args.num} server(s), scenario: {scenario})")
    server_mgr.prepare_mods(scenario)

    # Build compose file with services from both managers
    compose_mgr = DockerComposeManager(work_dir)
    jupyter_mgr = JupyterManager(work_dir)

    compose_mgr.add_services("jupyter", jupyter_mgr.get_services())
    compose_mgr.add_services(
        "factorio",
        server_mgr.get_services(args.num, scenario, max_agents=args.max_agents),
    )
    compose_mgr.write_compose()
    compose_mgr.up()

    # Calculate effective max_agents for display
    effective_max_agents = (
        args.max_agents if args.max_agents is not None else config.max_agents
    )

    # Print server info
    for i in range(args.num):
        rcon_port = config.get_rcon_port(f"server_{i}")
        game_port = config.get_game_port(i)
        print(f"  Server {i}: Game=localhost:{game_port}, RCON=localhost:{rcon_port}")
    print("\n📊 UDP Ports:")
    print(
        f"  Agent ports: {config.agent_port_base}-{config.agent_port_base + effective_max_agents - 1}"
    )
    print(f"  Snapshot port: {config.snapshot_port}")
    print("📓 Jupyter: http://localhost:8888")

    # Track experiment
    if args.name:
        tracker = SimpleExperimentTracker(work_dir)
        experiment_id = f"exp_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        tracker.add_experiment(experiment_id, args.name, args.num, scenario)
        print(f"📝 Experiment '{args.name}' tracked (ID: {experiment_id})")

    # Start hotreload watcher if requested (only for repo scenarios)
    if args.watch:
        print("\n🔥 Starting hot-reload watcher for scenario files...")
        scenario_dir = config.scenarios_dir / scenario
        watcher = HotreloadWatcher(scenario_dir, debounce_ms=2000)

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
    config = get_config()
    compose_mgr = DockerComposeManager(config.project_root)
    compose_mgr.down()
    print("✅ Services stopped")


def cmd_restart(args):
    """Restart all services."""
    config = get_config()
    compose_mgr = DockerComposeManager(config.project_root)
    compose_mgr.restart()
    print("✅ Services restarted")


def cmd_list(args):
    """List experiments."""
    config = get_config()
    tracker = SimpleExperimentTracker(config.project_root)

    experiments = tracker.list_experiments()
    if not experiments:
        print("No experiments found.")
        return

    print(f"Experiments ({len(experiments)}):")
    print(
        f"{'ID':<20} {'Name':<20} {'Servers':<8} {'Scenario':<15} {'Status':<10} {'Created'}"
    )
    print("-" * 100)
    for exp in experiments:
        created = datetime.fromisoformat(exp["created_at"]).strftime("%Y-%m-%d %H:%M")
        print(
            f"{exp['id']:<20} {exp['name']:<20} {exp['num_servers']:<8} {exp['scenario']:<15} {exp['status']:<10} {created}"
        )


def cmd_logs(args):
    """Show logs for a service."""
    config = get_config()
    compose_mgr = DockerComposeManager(config.project_root)
    compose_mgr.logs(args.service, follow=args.follow)


def cmd_server(args):
    """Control individual servers."""
    config = get_config()
    compose_mgr = DockerComposeManager(config.project_root)
    service_name = f"factorio_{args.server_id}"

    if args.action == "start":
        compose_mgr.start_service(service_name)
    elif args.action == "stop":
        compose_mgr.stop_service(service_name)
    elif args.action == "restart":
        compose_mgr.restart_service(service_name)


def cmd_list_scenarios(args):
    """List available scenarios from both repo and local directories."""
    config = get_config()
    scenarios = config.list_scenarios(include_local=True)

    if not scenarios:
        print("No scenarios found.")
        print(f"Repo directory: {config.scenarios_dir}")
        print(f"Local directory: {config.local_scenarios_dir}")
        return

    # Get repo-only scenarios for comparison
    repo_scenarios = set(config._list_scenarios_in_dir(config.scenarios_dir))

    print(f"Available scenarios ({len(scenarios)}):")
    print(f"{'Scenario':<25} {'Source':<10} {'Hot-reload':<10}")
    print("-" * 50)
    for scenario in sorted(scenarios):
        is_repo = scenario in repo_scenarios
        source = "repo" if is_repo else "local"
        hotreload = "✓" if is_repo else "✗"
        print(f"  {scenario:<23} {source:<10} {hotreload}")
    print("\nUsage: uv run fv server start --scenario <scenario_name>")
    print("Note: Only repo scenarios can be hot-reloaded with --watch.")


# =============================================================================
# Data Commands
# =============================================================================


def cmd_data_prune(args):
    """Prune data-raw-dump.json to factorio-data-dump.json."""
    config = get_config()
    instance = args.instance or "client"

    input_path = get_data_raw_path(instance)
    output_path = config.data_dump_path

    if not input_path.exists():
        print(
            f"❌ Error: data-raw-dump.json not found at {input_path}", file=sys.stderr
        )
        print("\n💡 Run Factorio with --dump-data to generate it:", file=sys.stderr)
        print("   uv run fv client dump-data", file=sys.stderr)
        sys.exit(1)

    print(f"📦 Pruning {input_path}")
    print(f"   Output: {output_path}")

    output, original_size, pruned_size = prune_data_raw(input_path, output_path)

    reduction = (1 - pruned_size / original_size) * 100
    print(
        f"\n✅ Pruned: {original_size / 1024 / 1024:.1f}MB → {pruned_size / 1024 / 1024:.1f}MB ({reduction:.1f}% reduction)"
    )
    print(f"   Saved to: {output}")


def cmd_data_refresh(args):
    """Full pipeline: find data-raw-dump.json and prune it."""
    instance = args.instance or "client"

    print(f"🔄 Refreshing data dump from {instance}...")

    try:
        output = refresh_data_dump(instance)
        print(f"\n✅ Data dump refreshed: {output}")
    except FileNotFoundError as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_instance_list(args):
    """List all Factorio instances and their status."""
    print("🔍 Checking Factorio instances...\n")

    instances = FactorioInstanceManager.list_available()

    print(
        f"{'Instance':<12} {'Type':<8} {'RCON Port':<12} {'Status':<10} {'Script Output'}"
    )
    print("-" * 80)

    for inst in instances:
        status = "✅ Active" if inst.test_connection() else "⬚ Inactive"
        print(
            f"{inst.name:<12} {inst.type:<8} {inst.rcon_port:<12} {status:<10} {inst.script_output_dir}"
        )


def cmd_instance_active(args):
    """Show the currently active Factorio instance."""
    try:
        instance = FactorioInstanceManager.get_active(require_single=False)
        print(f"✅ Active instance: {instance.name}")
        print(f"   Type: {instance.type}")
        print(f"   RCON: {instance.rcon_host}:{instance.rcon_port}")
        print(f"   Script output: {instance.script_output_dir}")
    except NoInstanceError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)
    except MultipleInstancesError as e:
        print(f"⚠️  {e}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="FactoryVerse: Run multiple Factorio servers with Jupyter",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command")

    # ========== CLIENT COMMAND ==========
    client_parser = subparsers.add_parser("client", help="Factorio client operations")
    client_subparsers = client_parser.add_subparsers(
        dest="client_action", help="Client action"
    )

    # Client launch subcommand
    client_launch_parser = client_subparsers.add_parser(
        "launch", help="Setup and launch Factorio client"
    )
    client_launch_parser.add_argument(
        "-s",
        "--scenario",
        default="test-ground",
        help="Scenario to load (default: test-ground)",
    )
    client_launch_parser.add_argument(
        "-f", "--force", action="store_true", help="Force re-setup of client"
    )
    client_launch_parser.add_argument(
        "-w",
        "--watch",
        action="store_true",
        help="Enable hot-reload watcher (repo scenarios only)",
    )
    client_launch_parser.add_argument(
        "--reset-ghosts", action="store_true", help="Reset all ghost entities state"
    )
    client_launch_parser.set_defaults(func=cmd_client_launch)

    # Client log subcommand
    client_log_parser = client_subparsers.add_parser(
        "log", help="Display Factorio client log file"
    )
    client_log_parser.add_argument(
        "-f", "--follow", action="store_true", help="Follow log file (like tail -f)"
    )
    client_log_parser.set_defaults(func=cmd_client_log)

    # Client dump-data subcommand
    client_dump_parser = client_subparsers.add_parser(
        "dump-data", help="Dump Factorio data.raw to JSON"
    )
    client_dump_parser.add_argument(
        "-s",
        "--scenario",
        default="test-ground",
        help="Scenario to use (default: test-ground)",
    )
    client_dump_parser.add_argument(
        "-f", "--force", action="store_true", help="Force re-setup of client"
    )
    client_dump_parser.set_defaults(func=cmd_client_dump_data)

    # ========== SERVER COMMAND ==========
    server_parser = subparsers.add_parser("server", help="Factorio server operations")
    server_subparsers = server_parser.add_subparsers(
        dest="server_action", help="Server action"
    )

    # Server start subcommand
    server_start_parser = server_subparsers.add_parser(
        "start", help="Setup client and start servers"
    )
    server_start_parser.add_argument(
        "-n", "--num", type=int, default=1, help="Number of servers (default: 1)"
    )
    server_start_parser.add_argument(
        "-s",
        "--scenario",
        default="test-ground",
        help="Scenario to load (default: test-ground). Use 'uv run fv server list-scenarios' to see available.",
    )
    server_start_parser.add_argument(
        "--max-agents",
        type=int,
        default=None,
        help="Max agents per server (default: from config, typically 10)",
    )
    server_start_parser.add_argument("--name", help="Experiment name (optional)")
    server_start_parser.add_argument(
        "-f", "--force", action="store_true", help="Force re-setup of client"
    )
    server_start_parser.add_argument(
        "-w",
        "--watch",
        action="store_true",
        help="Enable hot-reload watcher (repo scenarios only)",
    )
    server_start_parser.add_argument(
        "--reset-ghosts", action="store_true", help="Reset all ghost entities state"
    )
    server_start_parser.set_defaults(func=cmd_start)

    # Server stop subcommand
    server_stop_parser = server_subparsers.add_parser("stop", help="Stop all services")
    server_stop_parser.set_defaults(func=cmd_stop)

    # Server restart subcommand
    server_restart_parser = server_subparsers.add_parser(
        "restart", help="Restart all services"
    )
    server_restart_parser.set_defaults(func=cmd_restart)

    # Server list subcommand (experiments)
    server_list_parser = server_subparsers.add_parser("list", help="List experiments")
    server_list_parser.set_defaults(func=cmd_list)

    # Server list-scenarios subcommand
    server_scenarios_parser = server_subparsers.add_parser(
        "list-scenarios", help="List available scenarios"
    )
    server_scenarios_parser.set_defaults(func=cmd_list_scenarios)

    # Server logs subcommand
    server_logs_parser = server_subparsers.add_parser("logs", help="View logs")
    server_logs_parser.add_argument(
        "service", help="Service name (e.g., factorio_0, jupyter)"
    )
    server_logs_parser.add_argument(
        "-f", "--follow", action="store_true", help="Follow logs"
    )
    server_logs_parser.set_defaults(func=cmd_logs)

    # Server instance control subcommand
    server_instance_parser = server_subparsers.add_parser(
        "instance", help="Control individual server instances"
    )
    server_instance_parser.add_argument(
        "action", choices=["start", "stop", "restart"], help="Action"
    )
    server_instance_parser.add_argument("server_id", type=int, help="Server ID")
    server_instance_parser.set_defaults(func=cmd_server)

    # ========== DATA COMMAND ==========
    data_parser = subparsers.add_parser("data", help="Data dump management")
    data_subparsers = data_parser.add_subparsers(dest="data_action", help="Data action")

    # Data prune subcommand
    data_prune_parser = data_subparsers.add_parser(
        "prune", help="Prune data-raw-dump.json to factorio-data-dump.json"
    )
    data_prune_parser.add_argument(
        "-i",
        "--instance",
        default="client",
        help="Instance to read data-raw-dump.json from (default: client)",
    )
    data_prune_parser.set_defaults(func=cmd_data_prune)

    # Data refresh subcommand
    data_refresh_parser = data_subparsers.add_parser(
        "refresh", help="Find and prune data-raw-dump.json"
    )
    data_refresh_parser.add_argument(
        "-i",
        "--instance",
        default="client",
        help="Instance to read data-raw-dump.json from (default: client)",
    )
    data_refresh_parser.set_defaults(func=cmd_data_refresh)

    # ========== INSTANCE COMMAND ==========
    instance_parser = subparsers.add_parser("instance", help="Instance management")
    instance_subparsers = instance_parser.add_subparsers(
        dest="instance_action", help="Instance action"
    )

    # Instance list subcommand
    instance_list_parser = instance_subparsers.add_parser(
        "list", help="List all instances and their status"
    )
    instance_list_parser.set_defaults(func=cmd_instance_list)

    # Instance active subcommand
    instance_active_parser = instance_subparsers.add_parser(
        "active", help="Show active instance"
    )
    instance_active_parser.set_defaults(func=cmd_instance_active)

    args = parser.parse_args()

    if not hasattr(args, "func"):
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
