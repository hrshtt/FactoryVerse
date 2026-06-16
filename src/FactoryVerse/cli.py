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

from FactoryVerse.environment.config import get_config
from FactoryVerse.environment import (
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
from FactoryVerse.environment.tiers.base import TierError


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
            from FactoryVerse.environment.tiers.tier1_factorio import Tier1Factorio

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
        from FactoryVerse.infra.instance_manager import FactorioInstanceManager

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
                from FactoryVerse.environment.tiers.tier2_settings import Tier2Settings
                from FactoryVerse.environment.tiers.tier3_python import Tier3Python
                from FactoryVerse.environment.status import TierState

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
        # scenario is None if not provided (launches to main menu)
        scenario = args.scenario

        # Build configuration
        config = EnvironmentConfig(
            tier1=InfraConfig(mode=InfraMode.CLIENT),
            tier2=SettingsConfig(
                scenario=scenario,
                save_path=Path(args.save_file) if args.save_file else None,
                peaceful=not args.no_peaceful,
            ),
        )

        env = Environment(config=config)

        print("🚀 Starting Factorio client...")
        if scenario:
            print(f"   Scenario: {scenario}")
        else:
            print("   Mode: Main menu (no scenario)")
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
        if getattr(args, "save", None):
            print(f"   Loading save: {args.save} (scenario '{args.scenario}' used for mod prep only)")
        else:
            print(f"   Scenario: {args.scenario}")

        try:
            # Save loads must bypass tier2's implicit fresh-scenario start:
            # tier2.initialize() starts the server WITHOUT the save (it has no
            # server-save concept), and tier1's attach guard then no-ops the
            # explicit save-bearing call below (live-caught 2026-06-11:
            # `--save` silently booted a fresh scenario instead).
            up_to = (
                Tier.FACTORIO_INFRA if getattr(args, "save", None) else Tier.SETTINGS
            )
            await env.initialize(up_to=up_to)

            tier1 = env.tier1
            if tier1 is None:
                raise RuntimeError("Tier 1 not initialized")

            # Start servers
            await tier1.start_server(
                scenario=args.scenario,
                num_instances=args.num,
                save=getattr(args, "save", None),
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

    # Categorize scenarios by source
    repo_scenarios = set(config._list_scenarios_in_dir(config.scenarios_dir))
    inbuilt_scenarios = set()
    if config.inbuilt_scenarios_dir:
        inbuilt_scenarios = set(config._list_scenarios_in_dir(config.inbuilt_scenarios_dir))

    print(f"Available scenarios ({len(scenarios)}):\n")
    for scenario in sorted(scenarios):
        if scenario in repo_scenarios:
            source = "repo"
        elif scenario in inbuilt_scenarios:
            source = "inbuilt"
        else:
            source = "local"
        print(f"  {scenario:<25} [{source}]")


# =============================================================================
# Runtime Commands (Tier 3 + 4)
# =============================================================================


def cmd_connect(args):
    """Connect to a running Factorio instance."""

    async def _connect():
        env = Environment()

        print("🔗 Connecting to Factorio...")
        print(f"   Instance: {args.instance or 'auto-detect'}")

        try:
            # Use orchestrator's cross-tier connect pattern
            result = await env.orchestrator.connect_and_verify(instance=args.instance)

            if not result.get("success"):
                print(f"❌ Connection failed: {result.get('error')}")
                sys.exit(1)

            print(f"✅ Connected to {result['instance']}")
            print(f"   Game tick: {result['game_tick']}")

            agents = result.get("agents", [])
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

        except Exception as e:
            print(f"❌ Error: {e}", file=sys.stderr)
            sys.exit(1)
        finally:
            await env.shutdown()

    asyncio.run(_connect())


# =============================================================================
# Agent Commands (Full Stack Tier 1-6)
# =============================================================================


async def _detect_instance(args, scenario: str = None, auto_launch: bool = True) -> str:
    """Detect, validate, or auto-launch Factorio instance.

    Args:
        args: CLI args (must have .instance attribute)
        scenario: Scenario to launch with if auto-launching client
        auto_launch: If True, launch Factorio client when no instance found
    """
    from FactoryVerse.infra.instance_manager import FactorioInstanceManager

    if args.instance:
        all_instances = FactorioInstanceManager.list_available()
        valid_names = [i.name for i in all_instances]
        if args.instance not in valid_names:
            print(f"❌ Invalid instance: {args.instance}")
            print(f"   Available: {', '.join(valid_names)}")
            sys.exit(1)
        return args.instance

    detected = FactorioInstanceManager.detect_active()
    if detected:
        print(f"🔍 Auto-detected instance: {detected.name}")
        return detected.name

    if not auto_launch:
        print("❌ No running Factorio instance detected")
        print("   Start a server with: fv server start")
        print("   Or start client with: fv client start")
        sys.exit(1)

    # Auto-launch Factorio client
    print("🔍 No running Factorio instance detected — launching client...")
    await _auto_launch_client(scenario=scenario)

    # Wait for instance to become available
    for attempt in range(30):
        await asyncio.sleep(2)
        detected = FactorioInstanceManager.detect_active()
        if detected:
            print(f"✅ Client ready: {detected.name}")
            return detected.name
        if attempt % 5 == 4:
            print(f"   Waiting for client to start... ({(attempt + 1) * 2}s)")

    print("❌ Timed out waiting for Factorio client to start (60s)")
    print("   Try launching manually: fv client start --scenario lab-grid")
    sys.exit(1)


async def _auto_launch_client(scenario: str = None) -> None:
    """Launch Factorio client."""
    launch_scenario = scenario or "lab-grid"
    print(f"🚀 Starting Factorio client with scenario: {launch_scenario}")

    config = EnvironmentConfig(
        tier1=InfraConfig(mode=InfraMode.CLIENT),
        tier2=SettingsConfig(scenario=launch_scenario),
    )
    env = Environment(config=config)

    try:
        await env.initialize(up_to=Tier.SETTINGS)
        tier1 = env.tier1
        tier2 = env.tier2
        if tier1 is None or tier2 is None:
            raise RuntimeError("Failed to initialize tiers for client launch")
        launch_args = tier2.get_launch_args()
        await tier1.start_client(**launch_args)
    finally:
        # Don't shutdown — we want the client to keep running
        pass


def _build_environment_config(
    instance_name: str,
    scenario: str,
    provider: str,
    model: str,
    mode: str,
    agent_id: str,
    max_turns: int = None,
    task_name: str = None,
    is_eval: bool = False,
) -> EnvironmentConfig:
    """Build environment configuration for agent runs.

    Args:
        instance_name: Factorio instance (client/server_N)
        scenario: Scenario to load
        provider: LLM provider
        model: Model name
        mode: Interaction mode (assisted/autonomous)
        agent_id: Agent identifier
        max_turns: Maximum turns
        task_name: Task name for eval runs
        is_eval: If True, uses SessionMode.EVAL for .fv-output/evals/ directory
    """
    from FactoryVerse.environment.config import SessionMode

    if instance_name == "client":
        infra_mode = InfraMode.EXTERNAL
    else:
        infra_mode = InfraMode.SERVER

    # Determine session mode based on run type
    session_mode = SessionMode.EVAL if is_eval else SessionMode.LLM

    return EnvironmentConfig(
        tier1=InfraConfig(mode=infra_mode),
        tier2=SettingsConfig(scenario=scenario),
        tier3=PythonConfig(instance=instance_name, agent_id=agent_id),
        tier4=RuntimeConfig(
            variant=RuntimeVariant.FULL,
            agent_id=agent_id,
            provider=provider,
            model=model,
            mode=mode,
            session_mode=session_mode,
            task_name=task_name if is_eval else None,
        ),
        tier5=SpecificationConfig(
            include_api_reference=True,
            include_schema_reference=True,
            include_initial_state=True,
            task_name=task_name,
        ),
        tier6=InteractionConfig(
            mode=InteractionMode(mode),
            llm_provider=provider,
            model=model,
            max_turns=max_turns,
        ),
    )


def cmd_eval(args):
    """Run task evaluation using the Orchestrator.

    This is the new simplified command for running task evaluations.
    The Orchestrator handles initialization, task injection, verification, and cleanup.
    """

    async def _run():
        instance_name = await _detect_instance(args, scenario=args.scenario or "lab-grid")

        print("\n" + "=" * 60)
        print("📊 FactoryVerse Task Evaluation")
        print("=" * 60)
        print(f"   Task: {args.task}")
        print(f"   Model: {args.model}")
        print(f"   Provider: {args.provider}")
        print(f"   Instance: {instance_name}")
        print(f"   Agent ID: {args.agent_id}")
        print(f"   Scenario: {args.scenario or 'lab-grid'}")
        print(f"   Max turns: {args.max_turns or 'default'}")

        config = _build_environment_config(
            instance_name=instance_name,
            scenario=args.scenario or "lab-grid",
            provider=args.provider,
            model=args.model,
            mode="autonomous",
            agent_id=args.agent_id,
            max_turns=args.max_turns,
            task_name=args.task,
            is_eval=True,  # Use SessionMode.EVAL for .fv-output/evals/
        )

        env = Environment(config=config)

        try:
            # Initialize environment first to get session paths
            print("\n📦 Initializing environment...")
            await env.initialize(up_to=Tier.INTERACTION)

            # Display paths BEFORE the run starts (so user knows where to find outputs)
            tier4 = env.tier4
            if tier4 and tier4.session_dir:
                print("\n📁 Output Paths:")
                print(f"   Session Dir: {tier4.session_dir}")
                if tier4.trajectory_path:
                    print(f"   Trajectory:  {tier4.trajectory_path}")
                if tier4.notebook_path:
                    print(f"   Notebook:    {tier4.notebook_path}")
                if tier4.debug_log_path:
                    print(f"   Debug Log:   {tier4.debug_log_path}")
                # Config.json is written in _setup_eval_session_dir
                config_path = tier4.session_dir / "config.json"
                if config_path.exists():
                    print(f"   Config:      {config_path}")

            # Use Orchestrator for the task run
            print("\n🚀 Starting evaluation...")
            result = await env.orchestrator.run_task(
                task=args.task,
                model=args.model,
                provider=args.provider,
                max_turns=args.max_turns,
                cell=args.cell,
            )

            # Display results
            print("\n" + "=" * 60)
            print("📊 Evaluation Results")
            print("=" * 60)

            if result.task_success:
                print("✅ Task PASSED")
            else:
                print("❌ Task FAILED")
                if result.error:
                    print(f"   Error: {result.error}")

            print(f"\n   Total turns: {result.total_turns}")
            print(f"   Duration: {result.duration_seconds:.1f}s")

            if result.verification:
                v = result.verification
                print(f"\n   Verification:")
                print(f"      Target: {v.task_key}")
                print(f"      Automation produced: {v.automation_produced}")
                print(f"      Manual produced: {v.manual_produced}")
                print(f"      Automation ratio: {v.automation_ratio:.1%}")
                if v.failure_reason:
                    print(f"      Failure reason: {v.failure_reason}")

            # Final summary of output location (reference back to paths shown earlier)
            tier4 = env.tier4
            if tier4 and tier4.session_dir:
                print(f"\n📁 Artifacts saved to: {tier4.session_dir}")

        except KeyboardInterrupt:
            print("\n\n⚠️  Interrupted")
        except Exception as e:
            print(f"\n❌ Error: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            sys.exit(1)
        finally:
            await env.shutdown()

    asyncio.run(_run())


def cmd_freeplay(args):
    """Run open-ended freeplay using the Orchestrator.

    No specific task or verification - just let the agent explore and build.
    """

    async def _run():
        instance_name = await _detect_instance(args, scenario=args.scenario or "freeplay")

        print("\n" + "=" * 60)
        print("🎮 FactoryVerse Freeplay")
        print("=" * 60)
        print(f"   Model: {args.model}")
        print(f"   Provider: {args.provider}")
        print(f"   Instance: {instance_name}")
        print(f"   Max turns: {args.max_turns}")

        config = _build_environment_config(
            instance_name=instance_name,
            scenario=args.scenario or "freeplay",
            provider=args.provider,
            model=args.model,
            mode="autonomous",
            agent_id=args.agent_id,
            max_turns=args.max_turns,
        )

        env = Environment(config=config)

        try:
            print("\n🚀 Starting freeplay...")
            result = await env.orchestrator.run_freeplay(
                model=args.model,
                max_turns=args.max_turns,
                cell=args.cell,
                provider=args.provider,
            )

            print("\n" + "=" * 60)
            print("📊 Freeplay Results")
            print("=" * 60)

            if result.success:
                print("✅ Freeplay completed")
            else:
                print(f"❌ Error: {result.error}")

            print(f"\n   Total turns: {result.total_turns}")
            print(f"   Duration: {result.duration_seconds:.1f}s")

            if result.trajectory_path:
                print(f"\n📁 Trajectory: {result.trajectory_path}")

        except KeyboardInterrupt:
            print("\n\n⚠️  Interrupted")
        finally:
            await env.shutdown()

    asyncio.run(_run())


def cmd_agent(args):
    """Run LLM agent in assisted (interactive) mode.

    For autonomous task evaluation, use: fv eval --task <task>
    For autonomous freeplay, use: fv freeplay
    """
    import logging

    interrupt_count = 0

    async def _run():
        nonlocal interrupt_count

        instance_name = await _detect_instance(args, scenario=getattr(args, 'scenario', None))

        print("\n" + "=" * 60)
        print("🤖 FactoryVerse Agent - Assisted Mode")
        print("=" * 60)
        print(f"   Model: {args.model}")
        print(f"   Provider: {args.provider}")
        print(f"   Instance: {instance_name}")

        config = _build_environment_config(
            instance_name=instance_name,
            scenario=args.scenario or "freeplay",
            provider=args.provider,
            model=args.model,
            mode="assisted",
            agent_id=args.agent_id,
            max_turns=args.max_turns,
        )

        env = Environment(config=config)

        try:
            print("\n📦 Initializing environment...")
            await env.initialize(up_to=Tier.INTERACTION)
            print("✅ Ready")

            tier4 = env.tier4
            tier6 = env.tier6

            if tier4 and tier4.session_dir:
                print(f"\n📁 Session: {tier4.session_dir}")

                # Setup debug logging
                if tier4.debug_log_path:
                    file_handler = logging.FileHandler(tier4.debug_log_path)
                    file_handler.setLevel(logging.INFO)
                    file_handler.setFormatter(
                        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
                    )
                    logging.getLogger().addHandler(file_handler)
                    logging.getLogger("httpx").setLevel(logging.WARNING)

            # Interactive loop
            print("\n" + "-" * 60)
            print("Commands: /stats, /status, /reload, exit")
            print("-" * 60)

            orchestrator = tier6._orchestrator if tier6 else None

            while True:
                try:
                    user_input = input("\nUser > ").strip()

                    if not user_input:
                        continue

                    if user_input.lower() in ["exit", "quit"]:
                        break

                    if user_input.lower() == "/stats":
                        if orchestrator:
                            stats = orchestrator.get_statistics()
                            print(f"📊 Actions: {stats.get('total_actions', 0)}, "
                                  f"Success: {stats.get('success_count', 0)}, "
                                  f"Failed: {stats.get('failure_count', 0)}")
                        continue

                    if user_input.lower() == "/status":
                        if tier4:
                            print(f"📊 Modules: {', '.join(tier4._modules_loaded)}")
                        if orchestrator:
                            print(f"   Turn: {orchestrator.turn_number}")
                        continue

                    if user_input.lower().startswith("/reload"):
                        if tier4:
                            await tier4.reload_modules()
                            print("✅ Reloaded")
                        continue

                    # Run agent turn
                    if tier6:
                        response = await tier6.run_turn(user_input)
                        turn = orchestrator.turn_number if orchestrator else "?"
                        print(f"\n✅ Turn {turn}")
                        if response:
                            display = response[:300] + "..." if len(response) > 300 else response
                            print(f"Agent: {display}")

                except KeyboardInterrupt:
                    interrupt_count += 1
                    if interrupt_count >= 2:
                        break
                    print("\n⚠️  Press Ctrl+C again to exit")
                except EOFError:
                    break

        except TierError as e:
            print(f"❌ Error: {e}", file=sys.stderr)
            sys.exit(1)
        finally:
            print("\n🧹 Cleaning up...")
            await env.shutdown()
            if env.tier4 and env.tier4.session_dir:
                print(f"📁 Session saved: {env.tier4.session_dir}")

    asyncio.run(_run())


# =============================================================================
# Models Commands
# =============================================================================


def cmd_models_list(args):
    """List available LLM models from the configured provider."""
    from dotenv import load_dotenv

    load_dotenv()

    from FactoryVerse.infra.llm.client.factory import create_client_from_env

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

    from FactoryVerse.infra.llm.client.factory import create_client_from_env

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
# UI Commands
# =============================================================================


def cmd_ui(args):
    """Launch web-based Control Center."""
    from FactoryVerse.infra.ui.app import run_app

    print("🚀 Starting FactoryVerse Control Center...")
    print(f"   URL: http://{args.host}:{args.port}")

    run_app(host=args.host, port=args.port, native=args.native)


# =============================================================================
# Docs Commands
# =============================================================================


def cmd_docs_generate(args):
    """Generate API reference documentation."""
    from FactoryVerse.utils.docs.generator import write_api_reference
    from FactoryVerse.utils.docs.registry import reset_registry

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
    from FactoryVerse.utils.docs.reference import register_all_documentation
    from FactoryVerse.utils.docs.registry import get_registry, reset_registry
    from FactoryVerse.utils.docs.validators import CoverageValidator, ExampleValidator

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
# Dev Commands (certification / debugging tooling)
# =============================================================================


def cmd_dev_census(args):
    """Dump a ground-truth entity census from a running instance to JSONL."""
    from FactoryVerse.dev.census import CensusError, dump_census, parse_bounds

    try:
        bounds = parse_bounds(args.bounds)
    except ValueError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(2)

    print("📋 Census dump")
    print(f"   Instance: {args.instance}")
    print(f"   Force: {args.force} (+neutral resources: {not args.no_resources})")
    print(f"   Bounds: {bounds or 'all generated chunks'}")

    try:
        result = dump_census(
            instance=args.instance,
            force=args.force,
            include_resources=not args.no_resources,
            bounds=bounds,
            chunks_per_call=args.chunks_per_call,
        )
    except CensusError as e:
        print(f"❌ Census failed: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"\n✅ {len(result)} entities @ tick {result.tick} "
          f"({result.chunk_count} chunks, {result.rcon_calls} RCON calls)")
    for etype, n in sorted(result.counts_by_type.items(), key=lambda kv: -kv[1]):
        print(f"   {etype:<20} {n}")
    print(f"\n📁 {result.host_path}")


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
    client_start.add_argument("-s", "--scenario", help="Scenario to load (omit for main menu)")
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
    server_start.add_argument(
        "--save",
        help="Load this save instead of a fresh scenario start "
        "(name in .fv-output/server_N/saves/, written by game.server_save)",
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

    # ========== EVAL COMMAND (Task Evaluation) ==========
    eval_parser = subparsers.add_parser(
        "eval", help="Run task evaluation with verification"
    )
    eval_parser.add_argument(
        "-t", "--task", required=True, help="Task key (e.g., iron_plate_throughput)"
    )
    eval_parser.add_argument("-p", "--provider", default="prime_intellect")
    eval_parser.add_argument("--model", default="anthropic/claude-sonnet-4.6")
    eval_parser.add_argument("-s", "--scenario", default="lab-grid", help="Scenario")
    eval_parser.add_argument("-i", "--instance", help="Factorio instance")
    eval_parser.add_argument("--agent-id", default="agent_1")
    eval_parser.add_argument("--max-turns", type=int, help="Max turns (default: task's max)")
    eval_parser.add_argument("--cell", type=int, help="Lab-grid cell index")
    eval_parser.set_defaults(func=cmd_eval)

    # ========== FREEPLAY COMMAND ==========
    freeplay_parser = subparsers.add_parser(
        "freeplay", help="Run open-ended freeplay (no task/verification)"
    )
    freeplay_parser.add_argument("-p", "--provider", default="prime_intellect")
    freeplay_parser.add_argument("--model", default="anthropic/claude-sonnet-4.6")
    freeplay_parser.add_argument("-s", "--scenario", default="freeplay", help="Scenario")
    freeplay_parser.add_argument("-i", "--instance", help="Factorio instance")
    freeplay_parser.add_argument("--agent-id", default="agent_1")
    freeplay_parser.add_argument("--max-turns", type=int, default=200, help="Max turns")
    freeplay_parser.add_argument("--cell", type=int, help="Lab-grid cell index")
    freeplay_parser.set_defaults(func=cmd_freeplay)

    # ========== AGENT COMMAND (Assisted/Interactive) ==========
    agent_parser = subparsers.add_parser(
        "agent", help="Run LLM agent in assisted (interactive) mode"
    )
    agent_parser.add_argument("-p", "--provider", default="prime_intellect")
    agent_parser.add_argument("--model", default="anthropic/claude-sonnet-4.6")
    agent_parser.add_argument("-s", "--scenario", help="Scenario")
    agent_parser.add_argument("-i", "--instance", help="Factorio instance")
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

    # ========== DEV COMMANDS ==========
    dev_parser = subparsers.add_parser(
        "dev", help="Developer / certification tooling"
    )
    dev_sub = dev_parser.add_subparsers(dest="dev_action")

    # dev census
    dev_census = dev_sub.add_parser(
        "census",
        help="Dump ground-truth entity census to JSONL (read-only, chunked)",
    )
    dev_census.add_argument(
        "-i", "--instance", default="client", help="client or server_N"
    )
    dev_census.add_argument(
        "-f", "--force", default="player", help="Force to enumerate (default: player)"
    )
    dev_census.add_argument(
        "--bounds", help="Tile bounds x1,y1,x2,y2 (default: all generated chunks)"
    )
    dev_census.add_argument(
        "--no-resources",
        action="store_true",
        help="Skip neutral type='resource' entities",
    )
    dev_census.add_argument(
        "--chunks-per-call",
        type=int,
        default=64,
        help="32x32 chunks scanned per RCON call (default: 64)",
    )
    dev_census.set_defaults(func=cmd_dev_census)

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
