#!/usr/bin/env python3
"""FactoryVerse CLI (v2) - Environment-based orchestration.

This is the new CLI implementation that uses the Environment module
for all orchestration. The Environment module handles all tier
initialization and verification.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from .config import get_config
from .environment import (
    Environment,
    Tier,
    EnvironmentConfig,
    InfraConfig,
    SettingsConfig,
    PythonConfig,
    RuntimeConfig,
    SpecificationConfig,
    InteractionConfig,
    InfraMode,
    RuntimeVariant,
    InteractionMode,
)
from .environment.tiers.base import TierError


# =============================================================================
# Environment Status Command
# =============================================================================


def cmd_status(args):
    """Show environment status across all tiers."""

    async def _status():
        # Create environment but don't initialize
        env = Environment()

        print("🔍 FactoryVerse Environment Status\n")
        print("=" * 60)

        # Check Tier 1 prerequisites
        tier1 = env._tier1
        if tier1 is None:
            from .environment.tiers.tier1_factorio import Tier1Factorio

            tier1 = Tier1Factorio(env)

        if tier1 is None:
            raise RuntimeError("Tier 1 not initialized")
        await tier1.verify_prerequisites()

        print("\n📦 Tier 1: Factorio Infrastructure")
        if tier1._is_factorio_installed():
            print("   ✅ Factorio client: Installed")
        else:
            print("   ⬚ Factorio client: Not found")

        if tier1._is_docker_available():
            print("   ✅ Docker: Available")
        else:
            print("   ⬚ Docker: Not available")

        if tier1._check_mods_installed():
            print("   ✅ Mods: Available (fv_embodied_agent, fv_snapshot)")
        else:
            print("   ⬚ Mods: Not found")

        # Check for running instances
        print("\n🎮 Running Instances")
        from .infra.instance_manager import FactorioInstanceManager

        instances = FactorioInstanceManager.list_available()

        active_count = 0
        for inst in instances:
            if inst.test_connection():
                active_count += 1
                print(f"   ✅ {inst.name}: RCON {inst.rcon_port} - Active")

        if active_count == 0:
            print("   ⬚ No active Factorio instances")

        print("\n" + "=" * 60)

    asyncio.run(_status())


# =============================================================================
# Client Commands (Tier 1 + 2)
# =============================================================================


def cmd_client_start(args):
    """Start Factorio client with scenario or save file."""

    async def _start():
        # Build configuration
        config = EnvironmentConfig(
            tier1=InfraConfig(mode=InfraMode.CLIENT),
            tier2=SettingsConfig(
                scenario=args.scenario or "test-ground",
                save_path=Path(args.save_file) if args.save_file else None,
                peaceful=not args.no_peaceful,
            ),
        )

        env = Environment(config=config)

        print("🚀 Starting Factorio client...")
        print(f"   Scenario: {config.tier2.scenario}")
        if config.tier2.save_path:
            print(f"   Save: {config.tier2.save_path}")

        try:
            # Initialize up to Tier 2
            await env.initialize(up_to=Tier.SETTINGS)

            if env.tier1 is None or env.tier2 is None:
                raise RuntimeError("Environment not fully initialized")

            # Start the client
            tier2 = env.tier2
            tier1 = env.tier1
            if tier2 is None or tier1 is None:
                raise RuntimeError("Tiers not initialized")

            launch_args = tier2.get_launch_args()
            await tier1.start_client(**launch_args)

            print("✅ Client started successfully")

        except TierError as e:
            print(f"❌ Error: {e}", file=sys.stderr)
            sys.exit(1)

    asyncio.run(_start())


def cmd_client_stop(args):
    """Stop running Factorio client."""

    async def _stop():
        env = Environment(
            config=EnvironmentConfig(tier1=InfraConfig(mode=InfraMode.CLIENT))
        )

        # Just initialize tier 1 to get client manager
        await env.initialize(up_to=Tier.FACTORIO_INFRA)

        tier1 = env.tier1
        if tier1 is None:
            raise RuntimeError("Tier 1 not initialized")

        await tier1.stop_client(force=args.force)
        print("✅ Client stopped")

    asyncio.run(_stop())


def cmd_client_status(args):
    """Show Factorio client status."""

    async def _status():
        env = Environment(
            config=EnvironmentConfig(tier1=InfraConfig(mode=InfraMode.CLIENT))
        )

        await env.initialize(up_to=Tier.FACTORIO_INFRA)

        tier1 = env.tier1
        if tier1 is None:
            raise RuntimeError("Tier 1 not initialized")

        status = await tier1.verify_ready()

        if status.details.get("client_running"):
            print("✅ Client is running")
        else:
            print("⬚ Client is not running")

        print(f"   Mods installed: {status.details.get('mods_installed')}")

    asyncio.run(_status())


# =============================================================================
# Server Commands (Tier 1 + 2 with Docker)
# =============================================================================


def cmd_server_start(args):
    """Start Factorio server(s) with Docker."""

    async def _start():
        config = EnvironmentConfig(
            tier1=InfraConfig(
                mode=InfraMode.SERVER,
                server_count=args.num,
            ),
            tier2=SettingsConfig(
                scenario=args.scenario,
                peaceful=True,
            ),
        )

        env = Environment(config=config)

        print(f"🚀 Starting {args.num} Factorio server(s)...")
        print(f"   Scenario: {args.scenario}")

        try:
            await env.initialize(up_to=Tier.SETTINGS)

            tier1 = env.tier1
            if tier1 is None:
                raise RuntimeError("Tier 1 not initialized")

            # Start servers
            await tier1.start_server(
                scenario=args.scenario,
                num_instances=args.num,
            )

            # Print connection info
            infra_config = get_config()
            print("\n🌐 Server Information:")
            for i in range(args.num):
                rcon_port = infra_config.get_rcon_port(f"server_{i}")
                game_port = infra_config.get_game_port(i)
                print(f"   Server {i}: RCON {rcon_port}, Game {game_port}")

            print("\n✅ Servers started successfully")

        except TierError as e:
            print(f"❌ Error: {e}", file=sys.stderr)
            sys.exit(1)

    asyncio.run(_start())


def cmd_server_stop(args):
    """Stop all Factorio servers."""

    async def _stop():
        env = Environment(
            config=EnvironmentConfig(tier1=InfraConfig(mode=InfraMode.SERVER))
        )

        await env.initialize(up_to=Tier.FACTORIO_INFRA)
        await env.initialize(up_to=Tier.FACTORIO_INFRA)
        if env.tier1:
            await env.tier1.stop_server()
        print("✅ Servers stopped")

    asyncio.run(_stop())


def cmd_list_scenarios(args):
    """List available scenarios."""
    config = get_config()
    scenarios = config.list_scenarios(include_local=True)

    if not scenarios:
        print("No scenarios found.")
        return

    repo_scenarios = set(config._list_scenarios_in_dir(config.scenarios_dir))

    print(f"Available scenarios ({len(scenarios)}):\n")
    for scenario in sorted(scenarios):
        is_repo = scenario in repo_scenarios
        source = "repo" if is_repo else "local"
        print(f"  {scenario:<25} [{source}]")


# =============================================================================
# Runtime Commands (Tier 3 + 4)
# =============================================================================


def cmd_connect(args):
    """Connect to a running Factorio instance (Tier 3)."""

    async def _connect():
        config = EnvironmentConfig(
            tier1=InfraConfig(mode=InfraMode.CLIENT),
            tier3=PythonConfig(
                instance=args.instance,
                udp_enabled=not args.no_udp,
            ),
        )

        env = Environment(config=config)

        print("🔗 Connecting to Factorio...")
        print(f"   Instance: {args.instance or 'auto-detect'}")

        try:
            # Skip tier 1/2 initialization - just connect
            # We assume Factorio is already running
            from .environment.tiers.tier3_python import Tier3Python

            env._tier3 = Tier3Python(env)

            # Mock tier 2 as ready
            from .environment.tiers.tier2_settings import Tier2Settings
            from .environment.status import TierState

            env._tier2 = Tier2Settings(env)
            env._tier2._set_state(TierState.READY)

            await env._tier3.initialize()

            status = await env._tier3.verify_ready()

            if status.is_ready:
                print(f"✅ Connected to {env._tier3.instance}")
                print("   RCON: Connected")
                print(
                    f"   UDP: {'Listening' if status.details.get('udp_listening') else 'Disabled'}"
                )

                # Test with a simple command
                result = env._tier3.execute_lua("return game.tick")
                print(f"   Game tick: {result}")
            else:
                print(f"❌ Connection failed: {status.error}")
                sys.exit(1)

        except Exception as e:
            print(f"❌ Error: {e}", file=sys.stderr)
            sys.exit(1)
        finally:
            await env.shutdown()

    asyncio.run(_connect())


# =============================================================================
# Agent Commands (Full Stack Tier 1-6)
# =============================================================================


def cmd_agent(args):
    """Run LLM agent with full environment stack."""

    async def _run_agent():
        from .infra.instance_manager import FactorioInstanceManager
        from .llm.client.factory import create_client_from_env

        # =====================================================================
        # Runtime Discovery: Instance
        # =====================================================================
        instance_name = args.instance
        if not instance_name:
            # Auto-detect running instance
            detected = FactorioInstanceManager.detect_active()
            if detected:
                instance_name = detected.name
                print(f"🔍 Auto-detected instance: {instance_name}")
            else:
                print("❌ No running Factorio instance detected")
                print("   Start a server with: fv server start")
                print("   Or start client with: fv client start")
                sys.exit(1)
        else:
            # Validate provided instance
            all_instances = FactorioInstanceManager.list_available()
            valid_names = [i.name for i in all_instances]
            if instance_name not in valid_names:
                print(f"❌ Invalid instance: {instance_name}")
                print(f"   Available: {', '.join(valid_names)}")
                sys.exit(1)

        # =====================================================================
        # Runtime Discovery: Model
        # =====================================================================
        model_name = args.model
        if args.provider == "prime_intellect":
            # Query available models from the API
            try:
                from typing import cast, Any

                temp_client = create_client_from_env(
                    provider=args.provider,
                    model="placeholder",  # Doesn't matter for list_models
                )
                available_models = cast(Any, temp_client).list_models()
                if available_models:
                    print(f"📋 Available models: {', '.join(available_models[:5])}")
                    if model_name not in available_models:
                        # Try to find a matching model or use first available
                        default_model = available_models[0]
                        print(
                            f"⚠️  Model '{model_name}' not found, using '{default_model}'"
                        )
                        model_name = default_model
            except Exception as e:
                print(f"⚠️  Could not query models: {e}")

        # =====================================================================
        # Build Configuration
        # =====================================================================
        config = EnvironmentConfig(
            tier1=InfraConfig(mode=InfraMode.CLIENT),
            tier2=SettingsConfig(
                scenario=args.scenario or "freeplay",
            ),
            tier3=PythonConfig(
                instance=instance_name,
            ),
            tier4=RuntimeConfig(
                variant=RuntimeVariant.FULL,
                agent_id=args.agent_id,
            ),
            tier5=SpecificationConfig(
                include_api_reference=True,
                include_schema_reference=True,
            ),
            tier6=InteractionConfig(
                mode=InteractionMode(args.mode),
                llm_provider=args.provider,
                model=model_name,
                max_turns=args.max_turns,
            ),
        )

        print("🤖 Starting FactoryVerse Agent...")
        print(f"   Provider: {args.provider}")
        print(f"   Model: {model_name}")
        print(f"   Mode: {args.mode}")
        print(f"   Instance: {instance_name}")

        env = Environment(config=config)

        try:
            # Initialize all tiers
            print("\n📦 Initializing environment tiers...")
            await env.initialize(up_to=Tier.INTERACTION)

            print("✅ All tiers initialized")

            # Show status
            tier4 = env.tier4
            tier5 = env.tier5
            tier6 = env.tier6

            print("\n📊 Environment Status:")
            if tier4:
                print(f"   Tier 4 modules: {tier4._modules_loaded}")

            if tier5:
                print(
                    f"   Tier 5 prompt length: {len(tier5.system_prompt or '')} chars"
                )

            if tier6:
                print(f"   Tier 6 tools: {tier6._tools_registered}")

            # Run based on mode
            if args.mode == "autonomous":
                print("\n🚀 Starting autonomous agent loop...")
                if tier6:
                    await tier6.run_loop()
            else:
                print("\n💬 Entering assisted mode. Use keyboard to interact.")
                # Interactive loop would go here

        except TierError as e:
            print(f"\n❌ Tier Error: {e}", file=sys.stderr)
            sys.exit(1)
        except KeyboardInterrupt:
            print("\n\n⏹️  Agent stopped by user")
        finally:
            print("\n🧹 Cleaning up...")
            await env.shutdown()
            print("✅ Shutdown complete")

    asyncio.run(_run_agent())


# =============================================================================
# Models Commands
# =============================================================================


def cmd_models_list(args):
    """List available LLM models from the configured provider."""
    from dotenv import load_dotenv

    load_dotenv()

    from .llm.client.factory import create_client_from_env

    provider = args.provider or "prime_intellect"
    print(f"📋 Fetching models from {provider}...")

    try:
        client = create_client_from_env(provider=provider, model="placeholder")
        from typing import cast, Any

        models = cast(Any, client).list_models()

        if models:
            print(f"\nAvailable models ({len(models)}):\n")
            for i, model in enumerate(models, 1):
                print(f"  {i:2d}. {model}")
        else:
            print("⚠️  No models found or failed to fetch")
    except Exception as e:
        print(f"❌ Error fetching models: {e}")
        sys.exit(1)


def cmd_models_select(args):
    """Interactively select an LLM model."""
    from dotenv import load_dotenv

    load_dotenv()

    from .llm.client.factory import create_client_from_env

    provider = args.provider or "prime_intellect"
    print(f"📋 Fetching models from {provider}...")

    try:
        client = create_client_from_env(provider=provider, model="placeholder")
        from typing import cast, Any

        models = cast(Any, client).list_models()

        if not models:
            print("⚠️  No models available")
            return

        print(f"\nAvailable models ({len(models)}):\n")
        for i, model in enumerate(models, 1):
            print(f"  {i:2d}. {model}")

        print()
        try:
            choice = input("Enter number to select model (or q to quit): ").strip()
            if choice.lower() == "q":
                return

            idx = int(choice) - 1
            if 0 <= idx < len(models):
                selected = models[idx]
                print(f"\n✅ Selected: {selected}")
                print(f"\nRun with: fv agent --model {selected}")
            else:
                print("❌ Invalid selection")
        except (ValueError, EOFError):
            print("❌ Invalid input")

    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


# =============================================================================
# MCP Server Command
# =============================================================================


def cmd_mcp_server(args):
    """Start MCP server using Environment."""

    async def _run_mcp():
        config = EnvironmentConfig.for_mcp(instance=args.instance)
        env = Environment(config=config)

        print("🔌 Starting FactoryVerse MCP Server...")
        print("   Connect your IDE (Cursor, Claude Desktop, etc.)")

        try:
            await env.initialize(up_to=Tier.RUNTIME)
            print("✅ Environment ready for MCP")

            # TODO: Integrate with actual MCP server
            from .mcp_server import run_mcp_server

            await run_mcp_server()

        except KeyboardInterrupt:
            print("\n⏹️  MCP server stopped")
        finally:
            await env.shutdown()

    asyncio.run(_run_mcp())


# =============================================================================
# UI Commands
# =============================================================================


def cmd_ui(args):
    """Launch web-based Control Center."""
    from .ui.app import run_app

    print("🚀 Starting FactoryVerse Control Center...")
    print(f"   URL: http://{args.host}:{args.port}")

    run_app(host=args.host, port=args.port, native=args.native)


# =============================================================================
# Main Entry Point
# =============================================================================


def main():
    # Load environment variables from .env file
    from dotenv import load_dotenv

    load_dotenv()

    parser = argparse.ArgumentParser(
        description="FactoryVerse CLI (v2) - Environment-based orchestration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command")

    # ========== STATUS COMMAND ==========
    status_parser = subparsers.add_parser("status", help="Show environment status")
    status_parser.set_defaults(func=cmd_status)

    # ========== CLIENT COMMANDS ==========
    client_parser = subparsers.add_parser("client", help="Factorio client operations")
    client_sub = client_parser.add_subparsers(dest="client_action")

    # client start
    client_start = client_sub.add_parser("start", help="Start Factorio client")
    client_start.add_argument("-s", "--scenario", help="Scenario to load")
    client_start.add_argument("--save-file", help="Save file to load")
    client_start.add_argument(
        "--no-peaceful", action="store_true", help="Disable peaceful mode"
    )
    client_start.set_defaults(func=cmd_client_start)

    # client stop
    client_stop = client_sub.add_parser("stop", help="Stop Factorio client")
    client_stop.add_argument("--force", action="store_true", help="Force kill")
    client_stop.set_defaults(func=cmd_client_stop)

    # client status
    client_status = client_sub.add_parser("status", help="Show client status")
    client_status.set_defaults(func=cmd_client_status)

    # ========== SERVER COMMANDS ==========
    server_parser = subparsers.add_parser("server", help="Factorio server operations")
    server_sub = server_parser.add_subparsers(dest="server_action")

    # server start
    server_start = server_sub.add_parser("start", help="Start Factorio servers")
    server_start.add_argument(
        "-n", "--num", type=int, default=1, help="Number of servers"
    )
    server_start.add_argument(
        "-s", "--scenario", default="test-ground", help="Scenario"
    )
    server_start.set_defaults(func=cmd_server_start)

    # server stop
    server_stop = server_sub.add_parser("stop", help="Stop Factorio servers")
    server_stop.set_defaults(func=cmd_server_stop)

    # server list-scenarios
    server_scenarios = server_sub.add_parser("list-scenarios", help="List scenarios")
    server_scenarios.set_defaults(func=cmd_list_scenarios)

    # ========== CONNECT COMMAND ==========
    connect_parser = subparsers.add_parser(
        "connect", help="Connect to running Factorio"
    )
    connect_parser.add_argument("-i", "--instance", help="Instance (client/server_N)")
    connect_parser.add_argument("--no-udp", action="store_true", help="Disable UDP")
    connect_parser.set_defaults(func=cmd_connect)

    # ========== AGENT COMMAND ==========
    agent_parser = subparsers.add_parser("agent", help="Run LLM agent")
    agent_parser.add_argument(
        "-m", "--mode", choices=["autonomous", "assisted"], default="autonomous"
    )
    agent_parser.add_argument("-p", "--provider", default="prime_intellect")
    agent_parser.add_argument("--model", default="intellect-3")
    agent_parser.add_argument("-s", "--scenario", help="Scenario")
    agent_parser.add_argument("-i", "--instance", help="Instance")
    agent_parser.add_argument("--agent-id", default="agent_1")
    agent_parser.add_argument("--max-turns", type=int, help="Max turns")
    agent_parser.set_defaults(func=cmd_agent)

    # ========== MODELS COMMAND ==========
    models_parser = subparsers.add_parser("models", help="LLM model management")
    models_sub = models_parser.add_subparsers(dest="models_action")

    # models list
    models_list = models_sub.add_parser("list", help="List available models")
    models_list.add_argument("-p", "--provider", help="LLM provider")
    models_list.set_defaults(func=cmd_models_list)

    # models select
    models_select = models_sub.add_parser("select", help="Interactively select a model")
    models_select.add_argument("-p", "--provider", help="LLM provider")
    models_select.set_defaults(func=cmd_models_select)

    # ========== MCP COMMAND ==========
    mcp_parser = subparsers.add_parser("mcp", help="Start MCP server")
    mcp_parser.add_argument("-i", "--instance", help="Instance")
    mcp_parser.set_defaults(func=cmd_mcp_server)

    # ========== UI COMMAND ==========
    ui_parser = subparsers.add_parser("ui", help="Launch Control Center")
    ui_parser.add_argument("--host", default="0.0.0.0")
    ui_parser.add_argument("--port", type=int, default=8080)
    ui_parser.add_argument("--native", action="store_true")
    ui_parser.set_defaults(func=cmd_ui)

    # ========== PARSE AND EXECUTE ==========
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    # Handle subcommands that don't have their own function
    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
