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
        active_instances = []
        for inst in instances:
            if inst.test_connection():
                active_count += 1
                active_instances.append(inst)
                print(f"   ✅ {inst.name}: RCON {inst.rcon_port} - Active")

        if active_count == 0:
            print("   ⬚ No active Factorio instances")

        # Query game state from first active instance (Tier 3 methods)
        if active_instances:
            print("\n🤖 Game State (from first active instance)")
            try:
                from .environment.tiers.tier2_settings import Tier2Settings
                from .environment.tiers.tier3_python import Tier3Python
                from .environment.status import TierState

                # Setup minimal tier 2/3 to query game state
                env._tier2 = Tier2Settings(env)
                env._tier2._set_state(TierState.READY)

                # Configure tier 3 for the first active instance
                env.config.tier3.instance = active_instances[0].name
                env._tier3 = Tier3Python(env)
                await env._tier3.initialize()

                # Query game tick
                game_tick = env._tier3.get_game_tick()
                print(f"   Game tick: {game_tick}")

                # Query agents (Lua SSOT)
                agents = env._tier3.list_game_agents()
                if agents:
                    print(f"   Agents ({len(agents)}):")
                    for agent in agents:
                        name = agent.get("interface_name", "unknown")
                        port = agent.get("udp_port", "?")
                        valid = "✅" if agent.get("entity_valid", False) else "❌"
                        pos = agent.get("position", {})
                        pos_str = f"({pos.get('x', 0):.0f}, {pos.get('y', 0):.0f})" if pos else ""
                        print(f"      {valid} {name}: UDP {port} {pos_str}")
                else:
                    print("   Agents: None")

                # Query snapshot status
                try:
                    snapshot = env._tier3.get_snapshot_status()
                    if snapshot:
                        phase = snapshot.get("phase", "unknown")
                        print(f"   Snapshot: {phase}")
                except Exception:
                    pass  # Snapshot query might not be available

                await env._tier3.shutdown()

            except Exception as e:
                print(f"   ⚠️  Could not query game state: {e}")

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

                # Query game state using Tier 3 methods (Lua SSOT)
                game_tick = env._tier3.get_game_tick()
                print(f"   Game tick: {game_tick}")

                # Query agents
                agents = env._tier3.list_game_agents()
                if agents:
                    print(f"\n🤖 Agents in Factorio ({len(agents)}):")
                    for agent in agents:
                        name = agent.get("interface_name", "unknown")
                        port = agent.get("udp_port", "?")
                        valid = "✅" if agent.get("entity_valid", False) else "❌"
                        force = agent.get("force", "?")
                        pos = agent.get("position", {})
                        pos_str = f"at ({pos.get('x', 0):.0f}, {pos.get('y', 0):.0f})" if pos else ""
                        print(f"   {valid} {name}: UDP {port}, force={force} {pos_str}")
                else:
                    print("\n🤖 Agents: None (use 'fv agent' to create one)")

                # Query snapshot status
                try:
                    snapshot = env._tier3.get_snapshot_status()
                    if snapshot:
                        phase = snapshot.get("phase", "unknown")
                        print(f"\n📸 Snapshot status: {phase}")
                except Exception:
                    pass  # Snapshot might not be available
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
    import logging

    # Track interrupts for graceful shutdown
    interrupt_count = 0

    async def _run_agent():
        nonlocal interrupt_count

        from .infra.instance_manager import FactorioInstanceManager
        from .llm.client.factory import create_client_from_env
        from .utils.rcon_utils import validate_rcon_connection
        from .utils.port_utils import validate_udp_port, find_process_using_port

        # =====================================================================
        # Pre-flight: Load Infrastructure Config
        # =====================================================================
        infra_config = get_config()

        # =====================================================================
        # Pre-flight: Instance Discovery
        # =====================================================================
        instance_name = args.instance
        if not instance_name:
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
            all_instances = FactorioInstanceManager.list_available()
            valid_names = [i.name for i in all_instances]
            if instance_name not in valid_names:
                print(f"❌ Invalid instance: {instance_name}")
                print(f"   Available: {', '.join(valid_names)}")
                sys.exit(1)

        # =====================================================================
        # Pre-flight: RCON Connection Validation
        # =====================================================================
        print("\n🔍 Validating RCON connection...")
        # Get the instance object based on name
        if instance_name == "client":
            instance = FactorioInstanceManager.get_client(config=infra_config)
        elif instance_name.startswith("server_"):
            server_num = int(instance_name.split("_")[1])
            instance = FactorioInstanceManager.get_server(server_num, config=infra_config)
        else:
            # Fallback: try to find in available instances
            all_instances = FactorioInstanceManager.list_available()
            instance = next((i for i in all_instances if i.name == instance_name), None)
            if instance is None:
                print(f"❌ Could not find instance: {instance_name}")
                sys.exit(1)

        success, error = validate_rcon_connection(
            instance.rcon_host, instance.rcon_port, instance.rcon_password
        )
        if not success:
            print(f"❌ RCON connection failed: {error}")
            print(f"\n💡 Make sure Factorio is running with RCON enabled.")
            print(f"   Expected: {instance.rcon_host}:{instance.rcon_port}")
            sys.exit(1)
        print(f"✅ RCON connection validated ({instance.rcon_host}:{instance.rcon_port})")

        # =====================================================================
        # Pre-flight: UDP Port Validation
        # =====================================================================
        udp_port = infra_config.agent_port_base

        print(f"\n🔍 Validating UDP port {udp_port}...")
        success, error = validate_udp_port(udp_port)
        if not success:
            print(f"❌ UDP port validation failed: {error}")
            process_info = find_process_using_port(udp_port)
            if process_info:
                print(f"\n💡 Port is being used by: {process_info}")
            print(f"\n💡 To fix this:")
            print(f"   1. Kill the process using the port")
            print(f"   2. Or set a different port via FV_AGENT_UDP_PORT")
            sys.exit(1)
        print(f"✅ UDP port {udp_port} is available")

        # =====================================================================
        # Pre-flight: Model Discovery
        # =====================================================================
        model_name = args.model
        if args.provider == "prime_intellect":
            try:
                from typing import cast, Any
                temp_client = create_client_from_env(
                    provider=args.provider, model="placeholder"
                )
                available_models = cast(Any, temp_client).list_models()
                if available_models:
                    print(f"\n📋 Available models: {', '.join(available_models[:5])}")
                    if model_name not in available_models:
                        default_model = available_models[0]
                        print(f"⚠️  Model '{model_name}' not found, using '{default_model}'")
                        model_name = default_model
            except Exception as e:
                print(f"⚠️  Could not query models: {e}")

        # =====================================================================
        # Build Configuration
        # =====================================================================
        if instance_name == "client":
            infra_mode = InfraMode.EXTERNAL
        else:
            infra_mode = InfraMode.SERVER

        # Calculate agent-specific UDP port
        # This ensures Tier 3's UDP listener matches Tier 4's Lua agent registration
        agent_id = args.agent_id  # e.g., "agent_1"
        try:
            agent_index = int(agent_id.split("_")[1]) - 1  # agent_1 → 0
        except (ValueError, IndexError):
            agent_index = 0

        server_index = None
        if instance_name.startswith("server_"):
            try:
                server_index = int(instance_name.split("_")[1])
            except (ValueError, IndexError):
                pass

        agent_udp_port = infra_config.get_agent_port(agent_index, server_index)

        config = EnvironmentConfig(
            tier1=InfraConfig(mode=infra_mode),
            tier2=SettingsConfig(scenario=args.scenario or "freeplay"),
            tier3=PythonConfig(
                instance=instance_name,
                agent_id=args.agent_id,  # Must match tier4 for UDP port calculation
            ),
            tier4=RuntimeConfig(
                variant=RuntimeVariant.FULL,
                agent_id=args.agent_id,
                provider=args.provider,  # Pass provider for session directory structure
                model=model_name,  # Pass model for session directory structure
                mode=args.mode,  # Pass mode for session metadata
            ),
            tier5=SpecificationConfig(
                include_api_reference=True,
                include_schema_reference=True,
                include_initial_state=True,
            ),
            tier6=InteractionConfig(
                mode=InteractionMode(args.mode),
                llm_provider=args.provider,
                model=model_name,
                max_turns=args.max_turns,
            ),
        )

        print("\n" + "=" * 60)
        print("🤖 Starting FactoryVerse Agent")
        print("=" * 60)
        print(f"   Provider: {args.provider}")
        print(f"   Model: {model_name}")
        print(f"   Mode: {args.mode}")
        print(f"   Instance: {instance_name}")
        print(f"   Agent ID: {args.agent_id}")
        print(f"   Agent UDP Port: {agent_udp_port}")

        env = Environment(config=config)

        try:
            # Initialize all tiers with detailed progress
            print("\n📦 Initializing environment tiers...")
            try:
                await env.initialize(up_to=Tier.INTERACTION)
                print("✅ All tiers initialized")
            except Exception as init_error:
                print(f"\n❌ Tier initialization failed: {init_error}", file=sys.stderr)
                # Show which tiers succeeded
                print("\n   Tier Status:")
                if env.tier1:
                    print(f"   ✅ Tier 1 (Factorio Infra): {env.tier1._state}")
                if env.tier2:
                    print(f"   ✅ Tier 2 (Settings): {env.tier2._state}")
                if env.tier3:
                    status = "✅" if env.tier3.is_ready else "❌"
                    print(f"   {status} Tier 3 (Python Infra): {env.tier3._state}")
                    if env.tier3._error:
                        print(f"      Error: {env.tier3._error}")
                if env.tier4:
                    status = "✅" if env.tier4.is_ready else "❌"
                    print(f"   {status} Tier 4 (Runtime): {env.tier4._state}")
                    if env.tier4._error:
                        print(f"      Error: {env.tier4._error}")
                if env.tier5:
                    status = "✅" if env.tier5.is_ready else "❌"
                    print(f"   {status} Tier 5 (Specification): {env.tier5._state}")
                    if env.tier5._error:
                        print(f"      Error: {env.tier5._error}")
                if env.tier6:
                    status = "✅" if env.tier6.is_ready else "❌"
                    print(f"   {status} Tier 6 (Interaction): {env.tier6._state}")
                    if env.tier6._error:
                        print(f"      Error: {env.tier6._error}")

                # Show full traceback for debugging
                import traceback
                print("\n   Full traceback:", file=sys.stderr)
                traceback.print_exc()
                raise

            tier4 = env.tier4
            tier5 = env.tier5
            tier6 = env.tier6

            # =====================================================================
            # Session Information
            # =====================================================================
            print("\n📁 Session Information:")
            if tier4 and tier4.session_dir:
                print(f"   Session dir: {tier4.session_dir}")
                print(f"   Chat log: {tier4.chat_log_path}")
                print(f"   Debug log: {tier4.debug_log_path}")
                print(f"   System prompt: {tier4.system_prompt_path}")
                print(f"   Initial state: {tier4.initial_state_path}")

                # Configure debug logging to file
                debug_log = tier4.debug_log_path
                if debug_log:
                    file_handler = logging.FileHandler(debug_log)
                    file_handler.setLevel(logging.INFO)
                    file_handler.setFormatter(
                        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
                    )
                    logging.getLogger().addHandler(file_handler)
                    logging.getLogger().setLevel(logging.INFO)
                    # Suppress httpx logs to console
                    logging.getLogger("httpx").setLevel(logging.WARNING)

            # =====================================================================
            # Environment Status
            # =====================================================================
            print("\n📊 Environment Status:")
            if tier4:
                print(f"   Tier 4 modules: {', '.join(tier4._modules_loaded)}")
            if tier5:
                prompt_len = len(tier5.system_prompt or "")
                initial_len = len(tier5.initial_state or "")
                print(f"   Tier 5 system prompt: {prompt_len} chars")
                print(f"   Tier 5 initial state: {initial_len} chars")
            if tier6:
                print(f"   Tier 6 tools: {tier6._tools_registered}")

            # =====================================================================
            # Run Agent Loop
            # =====================================================================
            if args.mode == "autonomous":
                await _run_autonomous(env, tier6)
            else:
                await _run_assisted(env, tier6)

        except TierError as e:
            print(f"\n❌ Tier Error: {e}", file=sys.stderr)
            sys.exit(1)
        except KeyboardInterrupt:
            interrupt_count += 1
            if interrupt_count == 1:
                print("\n\n⚠️  Interrupt received. Cleaning up...")
            else:
                print("\n\n⚠️  Force exit")
        finally:
            print("\n🧹 Cleaning up...")
            await env.shutdown()
            print("✅ Shutdown complete")
            # Use env.tier4 instead of local variable (may not be set if init failed)
            if env.tier4 and env.tier4.session_dir:
                print(f"\n📁 Session saved to: {env.tier4.session_dir}")

    async def _run_autonomous(env, tier6):
        """Run agent in autonomous mode."""
        nonlocal interrupt_count

        max_turns = tier6._orchestrator.max_turns if tier6._orchestrator else None
        max_display = max_turns if max_turns else "∞"

        print(f"\n🚀 Starting autonomous agent loop (max turns: {max_display})...")
        print("Press Ctrl+C once to pause, twice to exit.\n")

        if tier6:
            try:
                await tier6.run_loop()
            except KeyboardInterrupt:
                interrupt_count += 1
                if interrupt_count == 1:
                    print("\n⏸️  Paused. Press Ctrl+C again to exit.")
                    return
            except Exception as e:
                print(f"\n❌ Error in autonomous loop: {e}", file=sys.stderr)
                import traceback
                tier4 = env.tier4
                if tier4 and tier4.debug_log_path:
                    print(f"   See debug log: {tier4.debug_log_path}", file=sys.stderr)
                # Log full traceback
                logger = logging.getLogger(__name__)
                logger.exception("Error in autonomous loop")
                # Show abbreviated traceback
                tb_lines = traceback.format_exc().split('\n')
                for line in tb_lines[-5:]:
                    if line.strip():
                        print(f"   {line}", file=sys.stderr)
                raise

    async def _run_assisted(env, tier6):
        """Run agent in assisted mode with interactive loop."""
        nonlocal interrupt_count

        print("\n" + "=" * 60)
        print("🤖 Agent Online - Assisted Mode")
        print("=" * 60)
        print("Commands:")
        print("  /stats              - Show action statistics")
        print("  /agents             - List agents in Factorio (Lua SSOT)")
        print("  /set_max_turns N    - Set max turns (or 'unlimited')")
        print("  /reload             - Reload Python modules")
        print("  /reload --lua       - Reload Python + Lua scripts")
        print("  /debug              - Toggle verbose debug output")
        print("  /status             - Show environment tier status")
        print("  exit, quit          - Exit the session")
        print("=" * 60 + "\n")

        debug_mode = False

        orchestrator = tier6._orchestrator if tier6 else None

        while True:
            try:
                user_input = input("\nUser > ").strip()

                if not user_input:
                    continue

                # Exit commands
                if user_input.lower() in ["exit", "quit"]:
                    print("👋 Exiting...")
                    break

                # Stats command
                if user_input.lower() == "/stats":
                    if orchestrator:
                        stats = orchestrator.get_statistics()
                        print(f"\n📊 Statistics:")
                        print(f"   Total actions: {stats.get('total_actions', 0)}")
                        print(f"   Successful: {stats.get('success_count', 0)}")
                        print(f"   Failed: {stats.get('failure_count', 0)}")
                        total = stats.get('total_actions', 0)
                        if total > 0:
                            rate = stats.get('success_count', 0) / total
                            print(f"   Success rate: {rate:.1%}")
                    continue

                # Set max turns command
                if user_input.lower().startswith("/set_max_turns"):
                    parts = user_input.split()
                    if len(parts) < 2:
                        current = orchestrator.max_turns if orchestrator else "unknown"
                        print(f"\n📊 Current max turns: {current or 'unlimited'}")
                        print("   Usage: /set_max_turns <number> or /set_max_turns unlimited")
                        continue

                    value = parts[1].lower()
                    if value in ["unlimited", "none", "inf"]:
                        if orchestrator:
                            orchestrator.set_max_turns(None)
                        print("✅ Max turns set to: unlimited")
                    else:
                        try:
                            max_turns = int(value)
                            if max_turns < 0:
                                print("❌ Max turns must be non-negative")
                                continue
                            if orchestrator:
                                orchestrator.set_max_turns(max_turns)
                                remaining = max_turns - orchestrator.turn_number
                                print(f"✅ Max turns set to: {max_turns}")
                                print(f"   Current turn: {orchestrator.turn_number}, Remaining: {remaining}")
                        except ValueError:
                            print(f"❌ Invalid value: '{parts[1]}'")
                    continue

                # Reload command
                if user_input.lower().startswith("/reload"):
                    reload_lua = "--lua" in user_input.lower() or "-l" in user_input.lower()
                    print("\n🔄 Reloading modules...")
                    try:
                        tier4 = env.tier4
                        if tier4:
                            await tier4.reload_modules()
                        print("✅ Python modules reloaded")
                        if reload_lua:
                            tier3 = env.tier3
                            if tier3 and tier3.rcon_helper:
                                tier3.rcon_helper.rcon_client.send_command(
                                    "/c game.reload_script(); game.print('Scripts reloaded')"
                                )
                            print("✅ Lua scripts reloaded")
                    except Exception as e:
                        print(f"❌ Reload failed: {e}")
                    continue

                # Debug toggle command
                if user_input.lower() == "/debug":
                    debug_mode = not debug_mode
                    status = "ON" if debug_mode else "OFF"
                    print(f"\n🔧 Debug mode: {status}")
                    if debug_mode:
                        # Set logging to DEBUG level for console
                        logging.getLogger().setLevel(logging.DEBUG)
                        # Add stream handler if not present
                        root = logging.getLogger()
                        has_stream = any(isinstance(h, logging.StreamHandler) for h in root.handlers)
                        if not has_stream:
                            console_handler = logging.StreamHandler()
                            console_handler.setLevel(logging.DEBUG)
                            console_handler.setFormatter(logging.Formatter("%(name)s - %(levelname)s - %(message)s"))
                            root.addHandler(console_handler)
                        print("   Verbose logging enabled - errors will show full details")
                    else:
                        logging.getLogger().setLevel(logging.WARNING)
                        print("   Verbose logging disabled")
                    continue

                # Agents command - list agents from Lua SSOT
                if user_input.lower() == "/agents":
                    tier3 = env.tier3
                    if tier3:
                        try:
                            game_tick = tier3.get_game_tick()
                            agents = tier3.list_game_agents()
                            print(f"\n🤖 Agents in Factorio (tick {game_tick}):")
                            if agents:
                                for agent in agents:
                                    name = agent.get("interface_name", "unknown")
                                    port = agent.get("udp_port", "?")
                                    valid = "✅" if agent.get("entity_valid", False) else "❌"
                                    force = agent.get("force", "?")
                                    pos = agent.get("position", {})
                                    pos_str = f"at ({pos.get('x', 0):.1f}, {pos.get('y', 0):.1f})" if pos else ""
                                    print(f"   {valid} {name}: UDP {port}, force={force} {pos_str}")
                            else:
                                print("   No agents found")
                        except Exception as e:
                            print(f"   ❌ Could not query agents: {e}")
                    else:
                        print("   ❌ Tier 3 not available")
                    continue

                # Status command - show tier status
                if user_input.lower() == "/status":
                    print("\n📊 Environment Status:")
                    tier3 = env.tier3
                    tier4 = env.tier4
                    tier5 = env.tier5

                    # Query game state from Lua (SSOT)
                    if tier3:
                        print(f"   Tier 3 (Python Infra):")
                        print(f"      RCON: {tier3.rcon_helper.rcon_client.is_connected if tier3.rcon_helper else 'N/A'}")
                        print(f"      UDP listener: {'active' if tier3._action_listener else 'inactive'}")
                        try:
                            game_tick = tier3.get_game_tick()
                            print(f"      Game tick: {game_tick}")
                            agents = tier3.list_game_agents()
                            print(f"      Agents in Factorio: {len(agents)}")
                        except Exception:
                            pass

                    if tier4:
                        print(f"   Tier 4 (Runtime):")
                        print(f"      Agent ID: {tier4.agent_id}")
                        print(f"      Session: {tier4.session_dir}")
                        print(f"      Modules: {', '.join(tier4._modules_loaded) if tier4._modules_loaded else 'none'}")
                        print(f"      Database: {'connected' if tier4.database else 'not connected'}")

                    if tier5:
                        print(f"   Tier 5 (Specification):")
                        print(f"      System prompt: {len(tier5.system_prompt or '')} chars")
                        print(f"      Initial state: {len(tier5.initial_state or '')} chars")

                    if tier6:
                        print(f"   Tier 6 (Interaction):")
                        print(f"      Orchestrator: {'ready' if tier6._orchestrator else 'not ready'}")
                        print(f"      Tools: {tier6._tools_registered}")
                        if orchestrator:
                            print(f"      Turn: {orchestrator.turn_number}")
                            print(f"      Max turns: {orchestrator.max_turns or 'unlimited'}")
                    continue

                # Run agent turn
                if tier6:
                    try:
                        response = await tier6.run_turn(user_input)
                        turn_num = orchestrator.turn_number if orchestrator else "?"
                        print(f"\n✅ Turn {turn_num} complete")
                        if response:
                            print(f"   Agent: {response[:200]}..." if len(response) > 200 else f"   Agent: {response}")
                        else:
                            print("   Agent: (no response)")

                        # Show action stats after each turn
                        if orchestrator:
                            stats = orchestrator.get_statistics()
                            if stats.get('failure_count', 0) > 0:
                                print(f"   ⚠️  Failures this session: {stats['failure_count']}")

                    except Exception as e:
                        print(f"\n❌ Error during turn: {e}", file=sys.stderr)
                        import traceback
                        # Get the debug log path to mention
                        tier4 = env.tier4
                        if tier4 and tier4.debug_log_path:
                            print(f"   See debug log for details: {tier4.debug_log_path}", file=sys.stderr)
                        # Also log the full traceback to debug log
                        logger = logging.getLogger(__name__)
                        logger.exception("Error during agent turn")
                        # Show abbreviated traceback on console for immediate debugging
                        tb_lines = traceback.format_exc().split('\n')
                        # Show last few lines of traceback (most relevant)
                        for line in tb_lines[-5:]:
                            if line.strip():
                                print(f"   {line}", file=sys.stderr)

            except KeyboardInterrupt:
                interrupt_count += 1
                if interrupt_count == 1:
                    print("\n\n⚠️  Interrupt received. Press Ctrl+C again to exit, or continue interacting.")
                    continue
                else:
                    print("\n\n👋 Exiting...")
                    break
            except EOFError:
                print("\n👋 EOF received, exiting...")
                break

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
# Docs Commands
# =============================================================================


def cmd_docs_generate(args):
    """Generate API reference documentation."""
    from .docs.generator import write_api_reference
    from .docs.registry import reset_registry

    # Reset registry to ensure clean state
    reset_registry()

    output_path = Path(args.output) if args.output else None

    print("📝 Generating API reference documentation...")

    try:
        path = write_api_reference(output_path)
        print(f"\n✅ Documentation generated: {path}")
    except Exception as e:
        print(f"❌ Error generating documentation: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_docs_validate(args):
    """Validate documentation coverage and examples."""
    from .docs.reference import register_all_documentation
    from .docs.registry import get_registry, reset_registry
    from .docs.validators import CoverageValidator, ExampleValidator

    reset_registry()
    register_all_documentation()

    registry = get_registry()

    print("🔍 Validating documentation...\n")

    # Coverage validation
    print("📊 Coverage Report:")
    coverage_validator = CoverageValidator(registry)
    coverage_report = coverage_validator.validate()
    print(coverage_report.summary())

    # Example syntax validation
    print("\n📝 Example Validation:")
    example_validator = ExampleValidator(registry)
    example_report = example_validator.validate_all_syntax()
    print(example_report.summary())

    # Exit with error if validation failed
    if not coverage_report.complete and args.strict:
        print("\n❌ Coverage validation failed (--strict mode)")
        sys.exit(1)

    if not example_report.all_valid:
        print("\n❌ Example validation failed")
        sys.exit(1)

    print("\n✅ All validations passed")


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

    # ========== DOCS COMMANDS ==========
    docs_parser = subparsers.add_parser("docs", help="Documentation operations")
    docs_sub = docs_parser.add_subparsers(dest="docs_action")

    # docs generate
    docs_generate = docs_sub.add_parser("generate", help="Generate API reference")
    docs_generate.add_argument(
        "-o", "--output",
        help="Output path (default: docs/for-llms/api_reference.md)",
    )
    docs_generate.set_defaults(func=cmd_docs_generate)

    # docs validate
    docs_validate = docs_sub.add_parser("validate", help="Validate documentation")
    docs_validate.add_argument(
        "--strict",
        action="store_true",
        help="Fail if coverage is incomplete",
    )
    docs_validate.set_defaults(func=cmd_docs_validate)

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
