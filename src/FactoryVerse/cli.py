"""FactoryVerse CLI — a thin front on the Environment orchestrator.

    fv client start|stop        local Factorio client with the mods
    fv server start|stop        headless Docker server(s)
    fv run                      drive an agent (freeplay, --task, or --interactive)
    fv docs generate            regenerate docs/for-llms/api_reference.md and schema_reference.md
    fv census                   ground-truth entity dump from a running instance
    fv campaign ...             supervised freeplay campaigns (create/status/prejoin/launch)

All run configuration is assembled by ``EnvironmentConfig.for_run`` so the CLI
holds no knowledge of the tier stack.
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from FactoryVerse.environment import (
    Environment,
    EnvironmentConfig,
    InfraConfig,
    InfraMode,
    SettingsConfig,
    Tier,
)
from FactoryVerse.environment.config import get_config
from FactoryVerse.environment.tiers.base import TierError


def _fail(message: str, code: int = 1) -> None:
    print(f"❌ {message}", file=sys.stderr)
    sys.exit(code)


# =============================================================================
# client / server
# =============================================================================


async def _launch_client(scenario, save_file=None, peaceful=True) -> None:
    config = EnvironmentConfig(
        tier1=InfraConfig(mode=InfraMode.CLIENT),
        tier2=SettingsConfig(
            scenario=scenario,
            save_path=Path(save_file) if save_file else None,
            peaceful=peaceful,
        ),
    )
    env = Environment(config=config)
    await env.initialize(up_to=Tier.SETTINGS)
    await env.tier1.start_client(**env.tier2.get_launch_args())


def cmd_client_start(args):
    print(f"🚀 Starting Factorio client ({args.scenario or 'main menu'})")
    try:
        asyncio.run(_launch_client(args.scenario, args.save_file, not args.no_peaceful))
    except TierError as e:
        _fail(str(e))
    print("✅ Client started")


def cmd_client_stop(args):
    async def _stop():
        env = Environment(config=EnvironmentConfig(tier1=InfraConfig(mode=InfraMode.CLIENT)))
        await env.initialize(up_to=Tier.FACTORIO_INFRA)
        await env.tier1.stop_client(force=args.force)

    asyncio.run(_stop())
    print("✅ Client stopped")


def cmd_server_start(args):
    async def _start():
        env = Environment(
            config=EnvironmentConfig(
                tier1=InfraConfig(mode=InfraMode.SERVER, server_count=args.num),
                tier2=SettingsConfig(scenario=args.scenario, peaceful=True),
            )
        )
        # A save load must bypass tier2's implicit fresh-scenario start; tier1's
        # attach guard would otherwise no-op the save-bearing call below.
        await env.initialize(up_to=Tier.FACTORIO_INFRA if args.save else Tier.SETTINGS)
        await env.tier1.start_server(
            scenario=args.scenario, num_instances=args.num, save=args.save
        )
        infra = get_config()
        for i in range(args.num):
            print(f"   server_{i}: RCON {infra.get_rcon_port(f'server_{i}')}, game {infra.get_game_port(i)}")

    print(f"🚀 Starting {args.num} Factorio server(s) — {args.save or args.scenario}")
    try:
        asyncio.run(_start())
    except TierError as e:
        _fail(str(e))
    print("✅ Servers started")


def cmd_server_stop(args):
    async def _stop():
        env = Environment(config=EnvironmentConfig(tier1=InfraConfig(mode=InfraMode.SERVER)))
        await env.initialize(up_to=Tier.FACTORIO_INFRA)
        await env.tier1.stop_server()

    asyncio.run(_stop())
    print("✅ Servers stopped")


# =============================================================================
# run
# =============================================================================


async def _resolve_instance(requested, scenario) -> str:
    """Validate a requested instance, auto-detect one, or launch a client."""
    from FactoryVerse.infra.instance_manager import FactorioInstanceManager

    if requested:
        names = [i.name for i in FactorioInstanceManager.list_available()]
        if requested not in names:
            _fail(f"Unknown instance {requested!r}; available: {', '.join(names)}")
        return requested

    detected = FactorioInstanceManager.detect_active()
    if detected:
        print(f"🔍 Using instance {detected.name}")
        return detected.name

    print(f"🔍 No running instance — launching client with {scenario}")
    await _launch_client(scenario)
    for attempt in range(30):
        await asyncio.sleep(2)
        detected = FactorioInstanceManager.detect_active()
        if detected:
            return detected.name
    _fail("Timed out waiting for the client (60s); try `fv client start` first")


async def _interactive(env) -> None:
    tier4, tier6 = env.tier4, env.tier6
    orchestrator = tier6._orchestrator if tier6 else None
    if tier4 and tier4.debug_log_path:
        handler = logging.FileHandler(tier4.debug_log_path)
        handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
        logging.getLogger().addHandler(handler)
        logging.getLogger("httpx").setLevel(logging.WARNING)

    print("\nCommands: /status, /reload, exit")
    interrupts = 0
    while True:
        try:
            text = input("\nUser > ").strip()
        except EOFError:
            return
        except KeyboardInterrupt:
            interrupts += 1
            if interrupts >= 2:
                return
            print("\n⚠️  Press Ctrl+C again to exit")
            continue
        if not text:
            continue
        if text.lower() in ("exit", "quit"):
            return
        if text.lower() == "/status":
            if tier4:
                print(f"Modules: {', '.join(tier4._modules_loaded)}")
            if orchestrator:
                stats = orchestrator.get_statistics()
                print(f"Turn {orchestrator.turn_number}; actions {stats.get('total_actions', 0)} "
                      f"(ok {stats.get('success_count', 0)}, failed {stats.get('failure_count', 0)})")
            continue
        if text.lower().startswith("/reload"):
            await tier4.reload_modules()
            print("✅ Reloaded")
            continue
        response = await tier6.run_turn(text)
        print(f"\n✅ Turn {orchestrator.turn_number if orchestrator else '?'}")
        if response:
            print(f"Agent: {response[:300] + '...' if len(response) > 300 else response}")


def cmd_run(args):
    """Drive an agent: freeplay by default, a verified task with --task,
    or a human-in-the-loop REPL with --interactive."""

    async def _run():
        scenario = args.scenario or ("lab-grid" if args.task else "freeplay")
        instance = await _resolve_instance(args.instance, scenario)
        config = EnvironmentConfig.for_run(
            instance=instance,
            scenario=scenario,
            provider=args.provider,
            model=args.model,
            agent_id=args.agent_id,
            max_turns=args.max_turns,
            task_name=args.task,
            interactive=args.interactive,
        )
        env = Environment(config=config)
        label = f"task {args.task}" if args.task else ("interactive" if args.interactive else "freeplay")
        print(f"\n🎮 fv run — {label} | {args.provider}/{args.model} | {instance} | {scenario}")
        try:
            await env.initialize(up_to=Tier.INTERACTION)
            if env.tier4 and env.tier4.session_dir:
                print(f"📁 Session: {env.tier4.session_dir}")

            if args.interactive:
                await _interactive(env)
                return

            if args.task:
                result = await env.orchestrator.run_task(
                    task=args.task, model=args.model, provider=args.provider,
                    max_turns=args.max_turns, cell=args.cell,
                )
                print("\n" + ("✅ Task PASSED" if result.task_success else "❌ Task FAILED"))
                if result.error:
                    print(f"   Error: {result.error}")
                if result.verification:
                    v = result.verification
                    print(f"   {v.task_key}: automated {v.automation_produced}, "
                          f"manual {v.manual_produced}, ratio {v.automation_ratio:.1%}")
                    if v.failure_reason:
                        print(f"   Failure reason: {v.failure_reason}")
            else:
                result = await env.orchestrator.run_freeplay(
                    model=args.model, max_turns=args.max_turns, cell=args.cell,
                    provider=args.provider,
                )
                print("\n" + ("✅ Freeplay completed" if result.success else f"❌ Error: {result.error}"))
            print(f"   Turns: {result.total_turns}, duration {result.duration_seconds:.1f}s")
        except KeyboardInterrupt:
            print("\n⚠️  Interrupted")
        except TierError as e:
            _fail(str(e))
        finally:
            await env.shutdown()
            if env.tier4 and env.tier4.session_dir:
                print(f"📁 Artifacts: {env.tier4.session_dir}")

    asyncio.run(_run())


# =============================================================================
# docs / census
# =============================================================================


def cmd_docs_generate(args):
    """Regenerate both agent-facing references. Needs no running instance."""
    from FactoryVerse.infra.llm.prompts.schema_reference import write_schema_reference
    from FactoryVerse.utils.docs.generator import write_api_reference
    from FactoryVerse.utils.docs.registry import reset_registry

    reset_registry()
    path = write_api_reference(Path(args.output) if args.output else None)
    print(f"✅ Wrote {path}")
    if not args.output:
        print(f"✅ Wrote {write_schema_reference()}")


def cmd_census(args):
    from FactoryVerse.dev.census import CensusError, dump_census, parse_bounds

    try:
        bounds = parse_bounds(args.bounds)
        result = dump_census(
            instance=args.instance,
            force=args.force,
            include_resources=not args.no_resources,
            bounds=bounds,
            chunks_per_call=args.chunks_per_call,
        )
    except (ValueError, CensusError) as e:
        _fail(str(e))
    print(f"✅ {len(result)} entities @ tick {result.tick} "
          f"({result.chunk_count} chunks, {result.rcon_calls} RCON calls)")
    for etype, n in sorted(result.counts_by_type.items(), key=lambda kv: -kv[1]):
        print(f"   {etype:<20} {n}")
    print(f"📁 {result.host_path}")


# =============================================================================
# parser
# =============================================================================

_PROVIDER_HELP = "LLM provider: prime_intellect (default), deepseek, openai, azure, local"
_MODEL_HELP = "Model id (default: the provider's default model, or $LLM_MODEL)"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fv", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command")

    client = sub.add_parser("client", help="Local Factorio client").add_subparsers(dest="action", required=True)
    p = client.add_parser("start", help="Start the client with the mods")
    p.add_argument("-s", "--scenario", help="Scenario to load (omit for main menu)")
    p.add_argument("--save-file", help="Save file to load")
    p.add_argument("--no-peaceful", action="store_true")
    p.set_defaults(func=cmd_client_start)
    p = client.add_parser("stop", help="Stop the client")
    p.add_argument("--force", action="store_true", help="Force kill")
    p.set_defaults(func=cmd_client_stop)

    server = sub.add_parser("server", help="Headless Docker server(s)").add_subparsers(dest="action", required=True)
    p = server.add_parser("start", help="Start server(s)")
    p.add_argument("-n", "--num", type=int, default=1, help="Number of servers")
    p.add_argument("-s", "--scenario", default="test-ground")
    p.add_argument("--save", help="Load this save (name in .fv-output/server_N/saves/) instead of a fresh scenario")
    p.set_defaults(func=cmd_server_start)
    p = server.add_parser("stop", help="Stop all servers")
    p.set_defaults(func=cmd_server_stop)

    p = sub.add_parser("run", help="Drive an agent (freeplay, --task, or --interactive)")
    p.add_argument("-t", "--task", help="Run this verified task instead of freeplay (e.g. iron_plate_throughput)")
    p.add_argument("--interactive", action="store_true", help="Human-in-the-loop REPL")
    p.add_argument("-p", "--provider", default="prime_intellect", help=_PROVIDER_HELP)
    p.add_argument("--model", default=None, help=_MODEL_HELP)
    p.add_argument("-s", "--scenario", help="Scenario (default: lab-grid for tasks, freeplay otherwise)")
    p.add_argument("-i", "--instance", help="Factorio instance (client / server_N); auto-detects or launches a client")
    p.add_argument("--agent-id", default="agent_1")
    p.add_argument("--max-turns", type=int, help="Max turns (default: task's max, or 200)")
    p.add_argument("--cell", type=int, help="Lab-grid cell index")
    p.set_defaults(func=cmd_run)

    docs = sub.add_parser("docs", help="Agent-facing reference docs").add_subparsers(dest="action", required=True)
    p = docs.add_parser("generate", help="Regenerate docs/for-llms/api_reference.md and schema_reference.md (no instance needed)")
    p.add_argument("-o", "--output", help="Output path")
    p.set_defaults(func=cmd_docs_generate)

    p = sub.add_parser("census", help="Ground-truth entity census from a running instance (read-only)")
    p.add_argument("-i", "--instance", default="client", help="client or server_N")
    p.add_argument("-f", "--force", default="player")
    p.add_argument("--bounds", help="Tile bounds x1,y1,x2,y2 (default: all generated chunks)")
    p.add_argument("--no-resources", action="store_true", help="Skip neutral resource entities")
    p.add_argument("--chunks-per-call", type=int, default=64)
    p.set_defaults(func=cmd_census)

    from FactoryVerse.evals.freeplay.cli import register as register_campaign

    register_campaign(sub)
    return parser


def main():
    from dotenv import load_dotenv

    load_dotenv()
    parser = build_parser()
    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(0)

    if getattr(args, "model", None) is None and getattr(args, "provider", None):
        from FactoryVerse.infra.llm.client.factory import default_model_for_provider

        args.model = os.getenv("LLM_MODEL") or default_model_for_provider(args.provider)
    if getattr(args, "max_turns", None) is None and getattr(args, "command", None) == "run" and not args.task:
        args.max_turns = 200

    args.func(args)


if __name__ == "__main__":
    main()
