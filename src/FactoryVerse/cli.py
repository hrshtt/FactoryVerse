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
from .infra.factorio_client_manager import FactorioClientManager
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


def cmd_client_start(args):
    """Start Factorio client with scenario or save file."""
    config = get_config()
    work_dir = config.project_root
    client_mgr = FactorioClientManager(work_dir)

    # Validate --watch only works with repo scenarios
    if args.watch and args.scenario and not config.is_repo_scenario(args.scenario):
        print(
            f"❌ Error: Cannot hot-reload scenario '{args.scenario}' - it's a local scenario.",
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

    # Resolve paths to absolute
    save_file = None
    if args.save_file:
        save_file = Path(args.save_file)
        if not save_file.is_absolute():
            save_file = work_dir / save_file
        save_file = save_file.resolve()

    map_gen_settings = None
    if args.map_gen_settings:
        map_gen_settings = Path(args.map_gen_settings)
        if not map_gen_settings.is_absolute():
            map_gen_settings = work_dir / map_gen_settings
        map_gen_settings = map_gen_settings.resolve()

    # Get project scenarios directory
    server_mgr = FactorioServerManager(work_dir, config)
    project_scenarios_dir = server_mgr.scenarios_dir

    # Start client
    try:
        client_mgr.start(
            scenario=args.scenario,
            save_file=save_file,
            map_gen_settings=map_gen_settings,
            new_map=args.new_map,
            map_name=args.map_name,
            force_setup=args.force,
            project_scenarios_dir=project_scenarios_dir,
        )
    except Exception as e:
        print(f"❌ Error starting client: {e}", file=sys.stderr)
        sys.exit(1)

    # Start hotreload watcher if requested (only for repo scenarios)
    if args.watch and args.scenario:
        print("\n🔥 Starting hot-reload watcher for scenario files...")
        scenario_dir = config.scenarios_dir / args.scenario
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


def cmd_client_stop(args):
    """Stop running Factorio client."""
    config = get_config()
    work_dir = config.project_root
    client_mgr = FactorioClientManager(work_dir)
    client_mgr.stop(force=args.force)


def cmd_client_restart(args):
    """Restart Factorio client."""
    config = get_config()
    work_dir = config.project_root
    client_mgr = FactorioClientManager(work_dir)

    # Resolve paths to absolute
    save_file = None
    if args.save_file:
        save_file = Path(args.save_file)
        if not save_file.is_absolute():
            save_file = work_dir / save_file
        save_file = save_file.resolve()

    map_gen_settings = None
    if args.map_gen_settings:
        map_gen_settings = Path(args.map_gen_settings)
        if not map_gen_settings.is_absolute():
            map_gen_settings = work_dir / map_gen_settings
        map_gen_settings = map_gen_settings.resolve()

    # Get project scenarios directory
    server_mgr = FactorioServerManager(work_dir, config)
    project_scenarios_dir = server_mgr.scenarios_dir

    try:
        client_mgr.restart(
            scenario=args.scenario,
            save_file=save_file,
            map_gen_settings=map_gen_settings,
            new_map=args.new_map,
            map_name=args.map_name,
            force_setup=args.force,
            project_scenarios_dir=project_scenarios_dir,
        )
    except Exception as e:
        print(f"❌ Error restarting client: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_client_status(args):
    """Show Factorio client status."""
    config = get_config()
    work_dir = config.project_root
    client_mgr = FactorioClientManager(work_dir)
    status = client_mgr.status()

    if status["running"]:
        print(f"✅ Client is running (PID: {status['pid']})")
        if status.get("state"):
            state = status["state"]
            if state.get("scenario"):
                print(f"   Scenario: {state['scenario']}")
            if state.get("save_file"):
                print(f"   Save file: {state['save_file']}")
    else:
        print("⬚ Client is not running")


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

    if not args.no_jupyter:
        compose_mgr.add_services("jupyter", jupyter_mgr.get_services())
    compose_mgr.add_services(
        "factorio",
        server_mgr.get_services(args.num, scenario, max_agents=args.max_agents),
    )
    compose_mgr.write_compose()
    compose_mgr.up()

    # Configure snapshot ports for each server (after they start)
    from FactoryVerse.utils.port_config import configure_all_server_snapshot_ports

    configure_all_server_snapshot_ports(args.num, config)

    # Calculate effective max_agents for display
    effective_max_agents = (
        args.max_agents if args.max_agents is not None else config.max_agents
    )

    # Print server info
    print("\n🌐 Server Information:")
    for i in range(args.num):
        rcon_port = config.get_rcon_port(f"server_{i}")
        game_port = config.get_game_port(i)
        snapshot_port = config.get_snapshot_port(f"server_{i}")
        agent_range = config.get_agent_port_range(server_index=i)

        print(f"  Server {i}:")
        print(f"    Game Port: localhost:{game_port}")
        print(f"    RCON Port: localhost:{rcon_port}")
        print(f"    Snapshot Port: {snapshot_port}")
        print(f"    Agent Ports: {agent_range[0]}-{agent_range[-1]}")

    print("\n📊 Client Ports:")
    print(f"  Snapshot Port: {config.client_snapshot_port}")
    agent_range_client = config.get_agent_port_range(server_index=None)
    print(f"  Agent Ports: {agent_range_client[0]}-{agent_range_client[-1]}")
    print("\n📓 Jupyter: http://localhost:8888")

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


def cmd_mcp_server(args):
    """Start MCP server for IDE integration."""
    import asyncio
    from .mcp_server import run_mcp_server

    print("Starting FactoryVerse MCP server...")
    print("Connect your IDE (Cursor, Claude Desktop, etc.) to use FactoryVerse tools.")
    print("Press Ctrl+C to stop.")
    try:
        asyncio.run(run_mcp_server())
    except KeyboardInterrupt:
        print("\nMCP server stopped.")
        sys.exit(0)


def cmd_ui(args):
    """Launch web-based Control Center (unified UI)."""
    from .ui.app import run_app

    print("🚀 Starting FactoryVerse Control Center...")
    print(f"   Host: {args.host}")
    print(f"   Port: {args.port}")
    print(f"   Native mode: {args.native}")
    print(f"\n   Open http://{args.host}:{args.port} in your browser\n")

    run_app(host=args.host, port=args.port, native=args.native)


def cmd_ui_agents(args):
    """Launch agent orchestrator UI."""
    from .ui.agent_orchestrator import run_agent_orchestrator

    print("🤖 Starting Agent Orchestrator UI...")
    print(f"   Host: {args.host}")
    print(f"   Port: {args.port}")
    print(f"   Native mode: {args.native}")
    print(f"\n   Open http://{args.host}:{args.port} in your browser\n")

    run_agent_orchestrator(host=args.host, port=args.port, native=args.native)


# =============================================================================
# Prompts Commands
# =============================================================================


def cmd_prompts_generate(args):
    """Generate complete system prompt."""
    from .llm.prompts import generate_system_prompt

    config = get_config()

    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        suffix = "with-examples" if args.with_examples else "core"
        output_path = (
            config.project_root
            / "docs"
            / "system-prompt"
            / f"factoryverse-system-prompt-v3-{suffix}.md"
        )

    # Generate prompt
    print("🔧 Generating system prompt...")
    prompt = generate_system_prompt(
        include_api_reference=not args.no_api,
        include_schema=not args.no_schema,
        include_examples=args.with_examples,
    )

    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(prompt)

    print(f"✅ System prompt generated: {output_path}")
    print(f"   Examples included: {args.with_examples}")
    print(f"   API reference: {not args.no_api}")
    print(f"   Schema reference: {not args.no_schema}")
    print(f"   Total size: {len(prompt):,} characters")
    print(f"   Total lines: {len(prompt.splitlines()):,} lines")


def cmd_prompts_api(args):
    """Generate API reference documentation."""
    from .llm.prompts.api_reference import write_api_reference

    config = get_config()
    output_path = config.project_root / args.output

    print("🔧 Generating API reference...")
    write_api_reference(output_path)


def cmd_prompts_schema(args):
    """Generate schema reference documentation."""
    from .llm.prompts.schema_reference import write_schema_reference

    config = get_config()
    output_path = config.project_root / args.output

    print("🔧 Generating schema reference...")
    write_schema_reference(output_path)


# =============================================================================
# Agent Command
# =============================================================================


def cmd_agent(args):
    """Run LLM agent orchestrator."""
    import os
    import asyncio
    from datetime import datetime
    from dotenv import load_dotenv

    # Load environment variables from .env file
    load_dotenv()

    # Determine provider - default to prime_intellect
    provider = args.provider or os.getenv("LLM_PROVIDER", "prime_intellect")

    # If no model specified and provider is prime_intellect, show model selection
    model_name = args.model
    if not model_name and provider == "prime_intellect":
        from openai import OpenAI

        api_key = os.getenv("PRIME_API_KEY") or os.getenv("PRIME_INTELLECT_API_KEY")
        if not api_key:
            print("❌ PRIME_API_KEY not set in environment")
            sys.exit(1)

        print("🔍 Fetching available models from Prime Intellect...")
        try:
            client = OpenAI(
                api_key=api_key, base_url="https://api.pinference.ai/api/v1"
            )
            models = client.models.list()
            available_models = [model.id for model in models.data]

            print(f"\n✅ Available models ({len(available_models)}):")
            for i, model in enumerate(available_models, 1):
                print(f"  {i}. {model}")

            while True:
                try:
                    choice = input("\nSelect model (number): ").strip()
                    idx = int(choice) - 1
                    if 0 <= idx < len(available_models):
                        model_name = available_models[idx]
                        break
                    else:
                        print("Invalid choice, try again")
                except ValueError:
                    print("Please enter a number")
        except Exception as e:
            print(f"❌ Error fetching models: {e}")
            sys.exit(1)
    elif not model_name:
        # For other providers, use a sensible default
        model_name = os.getenv("LLM_MODEL", "gpt-4o")

    print("🤖 Starting FactoryVerse Agent...")
    print(f"   Provider: {provider}")
    print(f"   Model: {model_name}")
    print(f"   Mode: {args.mode}")
    print(f"   Instance: {args.instance or 'auto-detect'}")
    print(f"   Agent ID: {args.agent_id}")

    # Create session configuration
    config = get_config()

    # Determine output directory
    # Note: model_name from Prime Intellect already includes provider prefix (e.g., "anthropic/claude-sonnet-4.5")
    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        run_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        output_dir = config.fv_output_dir / "runs" / model_name / run_id

    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"   Output: {output_dir}")

    # Create notebook path
    notebook_path = output_dir / "notebook.ipynb"

    # Run the agent
    async def run_agent():
        from .infra.session import FactoryVerseSession
        from .infra.execution import JupyterExecutor
        from .infra.boilerplate import Scope

        # Create executor
        executor = JupyterExecutor(notebook_path)

        # Create session
        session = FactoryVerseSession(
            session_id=f"agent_{args.agent_id}",
            executor=executor,
            scope=Scope.RUNTIME,
            instance=args.instance,
            agent_id=args.agent_id,
            session_dir=output_dir,
        )

        try:
            # Start session
            await session.start()
            print("\n✅ Session started. Runtime available.")

            if args.mode == "assisted":
                print("\n💬 Entering assisted mode. Type commands to execute.")
                print("   Type 'exit' or 'quit' to stop.")
                print("   Type 'reload' to hot-reload Python modules.")
                print()

                while True:
                    try:
                        user_input = input("fv> ").strip()

                        if not user_input:
                            continue

                        if user_input.lower() in ("exit", "quit"):
                            print("Exiting...")
                            break

                        if user_input.lower() == "reload":
                            await session.reload()
                            print("✅ Reloaded")
                            continue

                        # Execute the input as code
                        result = session.execute_dsl(user_input)
                        if result.output:
                            print(result.output)
                        if result.is_error:
                            print(f"Error: {result.error}")

                    except EOFError:
                        print("\nExiting...")
                        break

            else:
                # Autonomous mode - use AgentService
                print("\n🚀 Entering autonomous mode...")

                from .infra.services import AgentService

                # Create agent service
                service = AgentService(output_dir=output_dir.parent.parent)

                # Create session via service
                print("🎯 Creating agent session...")
                agent_session = await service.create_session(
                    model=model_name,
                    mode="autonomous",
                    instance=args.instance,
                    agent_id=args.agent_id,
                    provider=provider,
                    max_turns=args.max_turns,
                )

                agent = agent_session.orchestrator
                print(f"✅ Session created: {agent_session.session_id}")
                if args.max_turns:
                    print(f"   Max turns: {args.max_turns}")
                else:
                    print("   Max turns: unlimited")

                print("\n🤖 Agent ready! Starting autonomous execution...")
                print("   Press Ctrl+C to stop.\n")

                # Run autonomous loop
                turn = 0
                try:
                    while agent.has_turns_remaining():
                        turn += 1

                        if turn == 1:
                            user_msg = "You are now in control. Analyze the initial state and begin working towards automation goals. Start by exploring your surroundings and gathering resources."
                        else:
                            user_msg = "Continue with your current objective. You can change goals if you've completed your current task or if circumstances require adaptation."

                        try:
                            response = await service.run_turn(
                                agent_session.session_id, user_msg
                            )
                            print(f"\n--- Turn {turn} complete ---\n")
                        except Exception as e:
                            print(f"\n❌ Error in turn {turn}: {e}")
                            break

                except KeyboardInterrupt:
                    print("\n\n⚠️ Autonomous mode interrupted by user")

                print(f"\n📊 Final Statistics:")
                stats = agent.get_statistics()
                print(f"   Total turns: {turn}")
                print(f"   Total actions: {stats['total_actions']}")
                print(f"   Successful: {stats['success_count']}")
                print(f"   Failed: {stats['failure_count']}")

        finally:
            await service.stop_session(agent_session.session_id)
            print("\n✅ Session stopped.")

    try:
        asyncio.run(run_agent())
    except KeyboardInterrupt:
        print("\n\nInterrupted. Cleaning up...")
        sys.exit(130)


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

    # Client start subcommand
    client_start_parser = client_subparsers.add_parser(
        "start", help="Start Factorio client with scenario or save file"
    )
    client_start_parser.add_argument(
        "-s",
        "--scenario",
        help="Scenario to load (e.g., 'base/freeplay' or 'test-ground'). Use absolute path or scenario name.",
    )
    client_start_parser.add_argument(
        "--save-file",
        help="Absolute path to save file to load",
    )
    client_start_parser.add_argument(
        "--map-gen-settings",
        help="Absolute path to map generation settings JSON file",
    )
    client_start_parser.add_argument(
        "--new-map",
        action="store_true",
        help="Create a new map (requires --scenario or --map-gen-settings)",
    )
    client_start_parser.add_argument(
        "--map-name",
        help="Name for new map save file (default: auto-generated from scenario and timestamp)",
    )
    client_start_parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Force re-setup of client mods/scenarios",
    )
    client_start_parser.add_argument(
        "-w",
        "--watch",
        action="store_true",
        help="Enable hot-reload watcher (repo scenarios only)",
    )
    client_start_parser.add_argument(
        "--reset-ghosts", action="store_true", help="Reset all ghost entities state"
    )
    client_start_parser.set_defaults(func=cmd_client_start)

    # Client stop subcommand
    client_stop_parser = client_subparsers.add_parser(
        "stop", help="Stop running Factorio client"
    )
    client_stop_parser.add_argument(
        "--force",
        action="store_true",
        help="Force kill client (SIGKILL instead of SIGTERM)",
    )
    client_stop_parser.set_defaults(func=cmd_client_stop)

    # Client restart subcommand
    client_restart_parser = client_subparsers.add_parser(
        "restart", help="Restart Factorio client (uses last config if no args provided)"
    )
    client_restart_parser.add_argument(
        "-s",
        "--scenario",
        help="Scenario to load (overrides saved state)",
    )
    client_restart_parser.add_argument(
        "--save-file",
        help="Absolute path to save file to load (overrides saved state)",
    )
    client_restart_parser.add_argument(
        "--map-gen-settings",
        help="Absolute path to map generation settings JSON file (overrides saved state)",
    )
    client_restart_parser.add_argument(
        "--new-map",
        action="store_true",
        help="Create a new map (overrides saved state)",
    )
    client_restart_parser.add_argument(
        "--map-name",
        help="Name for new map save file",
    )
    client_restart_parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Force re-setup of client mods/scenarios",
    )
    client_restart_parser.set_defaults(func=cmd_client_restart)

    # Client status subcommand
    client_status_parser = client_subparsers.add_parser(
        "status", help="Show Factorio client status"
    )
    client_status_parser.set_defaults(func=cmd_client_status)

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
    server_start_parser.add_argument(
        "--no-jupyter",
        action="store_true",
        help="Skip starting Jupyter notebook server",
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

    # ========== PROMPTS COMMAND ==========
    prompts_parser = subparsers.add_parser(
        "prompts", help="LLM prompt and documentation generation"
    )
    prompts_subparsers = prompts_parser.add_subparsers(
        dest="prompts_action", help="Prompts action"
    )

    # prompts generate - generate full system prompt
    prompts_generate_parser = prompts_subparsers.add_parser(
        "generate", help="Generate complete system prompt"
    )
    prompts_generate_parser.add_argument(
        "-o",
        "--output",
        type=str,
        help="Output path (default: docs/system-prompt/factoryverse-system-prompt-v3-core.md)",
    )
    prompts_generate_parser.add_argument(
        "--with-examples",
        action="store_true",
        help="Include code examples from examples/ directory",
    )
    prompts_generate_parser.add_argument(
        "--no-api",
        action="store_true",
        help="Exclude API reference documentation",
    )
    prompts_generate_parser.add_argument(
        "--no-schema",
        action="store_true",
        help="Exclude schema reference documentation",
    )
    prompts_generate_parser.set_defaults(func=cmd_prompts_generate)

    # prompts api - generate API reference only
    prompts_api_parser = prompts_subparsers.add_parser(
        "api", help="Generate API reference documentation"
    )
    prompts_api_parser.add_argument(
        "-o",
        "--output",
        type=str,
        default="docs/for-llms/api_reference.md",
        help="Output path (default: docs/for-llms/api_reference.md)",
    )
    prompts_api_parser.set_defaults(func=cmd_prompts_api)

    # prompts schema - generate schema reference only
    prompts_schema_parser = prompts_subparsers.add_parser(
        "schema", help="Generate schema reference documentation"
    )
    prompts_schema_parser.add_argument(
        "-o",
        "--output",
        type=str,
        default="docs/for-llms/schema_reference.md",
        help="Output path (default: docs/for-llms/schema_reference.md)",
    )
    prompts_schema_parser.set_defaults(func=cmd_prompts_schema)

    # ========== AGENT COMMAND ==========
    agent_parser = subparsers.add_parser("agent", help="Run LLM agent")
    agent_parser.add_argument(
        "--model",
        type=str,
        help="LLM model name (default: from LLM_MODEL env or provider default)",
    )
    agent_parser.add_argument(
        "--provider",
        type=str,
        choices=["openai", "prime_intellect", "azure", "local"],
        help="LLM provider (default: from LLM_PROVIDER env or 'openai')",
    )
    agent_parser.add_argument(
        "--mode",
        choices=["assisted", "autonomous"],
        default="assisted",
        help="Agent mode (default: assisted)",
    )
    agent_parser.add_argument(
        "--max-turns",
        type=int,
        help="Maximum turns for autonomous mode (default: unlimited)",
    )
    agent_parser.add_argument(
        "--instance",
        type=str,
        help="Factorio instance to connect to (default: auto-detect)",
    )
    agent_parser.add_argument(
        "--agent-id",
        type=str,
        default="agent_1",
        help="Agent identifier (default: agent_1)",
    )
    agent_parser.add_argument(
        "-o",
        "--output-dir",
        type=str,
        help="Output directory for run artifacts (default: .fv-output/runs/)",
    )
    agent_parser.set_defaults(func=cmd_agent)

    mcp_parser = subparsers.add_parser(
        "mcp", help="Start MCP server for IDE integration"
    )
    mcp_parser.set_defaults(func=cmd_mcp_server)

    # ========== UI COMMAND ==========
    ui_parser = subparsers.add_parser(
        "ui", help="Launch FactoryVerse Control Center (unified web UI)"
    )
    ui_parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host to bind to (default: 127.0.0.1)",
    )
    ui_parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port to run on (default: 8080)",
    )
    ui_parser.add_argument(
        "--native",
        action="store_true",
        help="Open in native window (requires pywebview)",
    )
    ui_parser.set_defaults(func=cmd_ui)

    # ========== UI AGENTS COMMAND (LEGACY) ==========
    ui_agents_parser = subparsers.add_parser(
        "ui-agents", help="(Deprecated) Launch agent orchestrator UI - use 'ui' instead"
    )
    ui_agents_parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host to bind to (default: 127.0.0.1)",
    )
    ui_agents_parser.add_argument(
        "--port",
        type=int,
        default=8082,
        help="Port to run on (default: 8082)",
    )
    ui_agents_parser.add_argument(
        "--native",
        action="store_true",
        help="Open in native window (requires pywebview)",
    )
    ui_agents_parser.set_defaults(func=cmd_ui_agents)

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
