"""`fv campaign` — external-harness freeplay campaigns.

Kept separate from the main CLI: this surface belongs to the campaign
supervisor and is expected to be reshaped by the Turn Contract plan
(docs/architecture/TURN_CONTRACT_DEFERRED.md). Registered via ``register``.
"""

import asyncio
import json
import sys
from pathlib import Path

from FactoryVerse.environment.config import get_config


def _store(campaign_id: str):
    from FactoryVerse.evals.freeplay import FreeplayCampaignStore

    return FreeplayCampaignStore(get_config().fv_output_dir / "freeplay", campaign_id)


def cmd_create(args):
    """Create an immutable freeplay campaign manifest without launching it."""
    from FactoryVerse.evals.freeplay.supervisor import FreeplaySupervisor

    store = _store(args.campaign)
    manifest = FreeplaySupervisor.create_campaign(
        store,
        repo_root=get_config().project_root,
        infra_config=get_config(),
        seed=args.seed,
        agent_id=args.agent_id,
        harness=args.harness,
        model=args.model,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    print(f"\nCampaign created: {store.paths.root}")


def cmd_status(args):
    """Print campaign lifecycle, checkpoint, and runtime-session state."""
    store = _store(args.campaign)
    payload = {
        "manifest": store.manifest(),
        "state": store.state(),
        "checkpoints": store.checkpoint_records(),
        "runtime_sessions": list(store.iter_sessions()),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


def cmd_prejoin(args):
    """Read-only comparison of campaign server mods and installed client mods."""
    from FactoryVerse.evals.freeplay.prejoin import (
        compare_campaign_client_mods,
        format_prejoin_mod_compatibility,
    )
    from FactoryVerse.infra.factorio_client_setup import get_client_mod_path

    store = _store(args.campaign)
    client_mod_dir = (
        Path(args.client_mod_dir) if args.client_mod_dir else get_client_mod_path()
    )
    result = compare_campaign_client_mods(
        server_mod_dir=store.paths.server_mods,
        client_mod_dir=client_mod_dir,
        campaign_manifest=store.manifest(),
    )
    if args.json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    else:
        print(format_prejoin_mod_compatibility(result))
    exit_code = {"match": 0, "mismatch": 1, "indeterminate": 2}[result.status.value]
    if exit_code:
        raise SystemExit(exit_code)


def cmd_watch(args):
    """Run the event-driven, read-only Codex campaign operator."""
    from FactoryVerse.evals.freeplay.operator_controller import (
        OperatorSchedule,
        run_freeplay_operator,
    )

    async def _run():
        store = _store(args.campaign)
        schedule = OperatorSchedule(
            min_interval_seconds=args.min_interval,
            max_silence_seconds=args.max_silence,
            debounce_seconds=args.debounce,
            inference_grace_seconds=args.inference_grace,
            execution_grace_seconds=args.execution_grace,
        )
        decision = await run_freeplay_operator(
            store,
            model=args.model,
            objective=args.objective,
            codex_bin=args.codex_bin,
            schedule=schedule,
            request_timeout_seconds=args.app_server_timeout,
            turn_timeout_seconds=args.operator_turn_timeout,
            once=args.once,
            new_thread=args.new_thread,
        )
        print(json.dumps(decision, indent=2, sort_keys=True))

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        print("Freeplay operator stopped; the campaign was left running.", file=sys.stderr)


def cmd_launch(args):
    """Launch/resume a campaign and serve its single-owner actor protocol."""
    from FactoryVerse.evals.freeplay.runtime_host import FreeplayRuntimeHost, PROTOCOL_PREFIX
    from FactoryVerse.evals.freeplay.supervisor import FreeplaySupervisor

    async def _run():
        store = _store(args.campaign)
        if not store.exists:
            FreeplaySupervisor.create_campaign(
                store,
                repo_root=get_config().project_root,
                infra_config=get_config(),
                seed=args.seed,
                agent_id=args.agent_id,
                harness=args.harness,
                model=args.model,
            )
            print(f"Created campaign: {store.paths.root}", file=sys.stderr)

        supervisor = FreeplaySupervisor(
            store, repo_root=get_config().project_root, harness=args.harness, model=args.model
        )
        try:
            preflight = await supervisor.start(resume=args.resume)
            host = FreeplayRuntimeHost(
                supervisor,
                default_timeout=args.execution_timeout,
                maximum_timeout=args.maximum_execution_timeout,
            )
            print(
                "Freeplay runtime ready. Actor operations are status/execute; "
                "closing stdin asks the supervisor to finalize. "
                "Send one JSON object per stdin line; "
                f"machine responses begin with {PROTOCOL_PREFIX!r}.",
                file=sys.stderr,
                flush=True,
            )
            result = await host.serve_stdio(preflight)
            host._emit({"event": "closed", "result": result})
        except KeyboardInterrupt:
            if supervisor.environment is not None:
                result = await supervisor.finish(reason="operator_interrupt", checkpoint=True)
                FreeplayRuntimeHost._emit({"event": "closed", "result": result})
        except Exception as exc:
            FreeplayRuntimeHost._emit(
                {
                    "event": "launch_failed",
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "campaign_id": args.campaign,
                }
            )
            raise

    asyncio.run(_run())


def cmd_codex(args):
    """Run a supervised freeplay campaign with a persistent Codex app-server thread."""
    from FactoryVerse.evals.freeplay.codex_runner import (
        CodexAppServerActionClient,
        CodexFreeplayRunner,
        codex_harness_configuration,
        supervisor_owned_codex_configuration,
    )
    from FactoryVerse.evals.freeplay.codex_context import freeplay_goal
    from FactoryVerse.evals.freeplay.supervisor import (
        FREEPLAY_STARTING_INVENTORY,
        NOTIFICATION_DEBUG_RAW_INVENTORY,
        OFFSHORE_PUMP_DEBUG_INVENTORY,
        FreeplaySupervisor,
    )

    async def _run():
        store = _store(args.campaign)
        workspace = store.paths.root / "harness-workspace"
        control_dir = store.paths.root / "harness-control"
        offshore_pump_debug = bool(getattr(args, "offshore_pump_debug", False))
        task_objective = freeplay_goal(
            notification_debug=args.notification_debug,
            offshore_pump_debug=offshore_pump_debug,
            factory_debug=args.factory_debug,
        )
        client = CodexAppServerActionClient(
            executable=args.codex_bin,
            model=args.model,
            workspace=workspace,
            control_dir=control_dir,
            timeout_seconds=args.codex_timeout,
            task_objective=task_objective,
        )
        codex_version = await client.version()
        harness = f"codex-cli/{codex_version.rsplit(' ', 1)[-1]}"
        harness_configuration = supervisor_owned_codex_configuration(
            codex_harness_configuration(
                codex_version=codex_version,
                max_turns=args.max_turns,
                checkpoint_every=args.checkpoint_every,
                codex_timeout=args.codex_timeout,
                execution_timeout=args.execution_timeout,
                maximum_execution_timeout=args.maximum_execution_timeout,
                notification_debug=args.notification_debug,
                factory_debug=args.factory_debug,
            ),
            task_objective,
        )
        harness_configuration["offshore_pump_debug"] = offshore_pump_debug

        if not store.exists:
            initial_inventory = dict(FREEPLAY_STARTING_INVENTORY)
            if args.notification_debug:
                initial_inventory.update(NOTIFICATION_DEBUG_RAW_INVENTORY)
            if offshore_pump_debug:
                initial_inventory.update(OFFSHORE_PUMP_DEBUG_INVENTORY)
            FreeplaySupervisor.create_campaign(
                store,
                repo_root=get_config().project_root,
                infra_config=get_config(),
                seed=args.seed,
                agent_id=args.agent_id,
                harness=harness,
                model=args.model,
                harness_configuration=harness_configuration,
                initial_inventory=initial_inventory,
            )
            print(f"Created campaign: {store.paths.root}", file=sys.stderr)
        elif store.manifest().get("harness_configuration") != harness_configuration:
            raise RuntimeError(
                "Codex runner arguments differ from the immutable campaign harness_configuration"
            )

        supervisor = FreeplaySupervisor(
            store, repo_root=get_config().project_root, harness=harness, model=args.model
        )
        runner = None
        try:
            preflight = await supervisor.start(resume=args.resume)
            runner = CodexFreeplayRunner(
                supervisor,
                client,
                max_turns=args.max_turns,
                checkpoint_every=args.checkpoint_every,
                execution_timeout=args.execution_timeout,
                maximum_execution_timeout=args.maximum_execution_timeout,
                notification_debug=args.notification_debug,
                offshore_pump_debug=offshore_pump_debug,
                factory_debug=args.factory_debug,
            )
            await client.start()
            try:
                runner_result = await runner.run(preflight)
            finally:
                await client.close()
            campaign_result = await supervisor.finish(
                reason=runner_result["reason"],
                checkpoint=True,
                execution_count=runner_result["session_executions"],
            )
            print(
                json.dumps(
                    {
                        "campaign": campaign_result,
                        "codex": runner_result,
                        "workspace": str(workspace),
                        "control_artifacts": str(control_dir),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        except asyncio.CancelledError:
            if supervisor.environment is not None:
                await supervisor.finish(
                    reason="operator_interrupt",
                    checkpoint=True,
                    execution_count=(runner.actor.execution_count if runner else 0),
                )
            raise
        except Exception as exc:
            if supervisor.environment is not None:
                try:
                    await supervisor.finish(
                        reason=f"codex_harness_error: {type(exc).__name__}: {exc}",
                        checkpoint=True,
                        execution_count=(runner.actor.execution_count if runner else 0),
                    )
                except Exception:
                    pass
            raise

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        print("Codex freeplay run interrupted and finalized.", file=sys.stderr)


def register(subparsers) -> None:
    """Attach `campaign` and its subcommands to the top-level parser."""
    parser = subparsers.add_parser(
        "campaign", help="External-harness freeplay campaigns (create/launch/codex/watch)"
    )
    sub = parser.add_subparsers(dest="campaign_action", required=True)

    def _campaign_identity(p, model_required=False):
        p.add_argument("--campaign", required=True)
        p.add_argument("--seed", type=int, default=44340)
        p.add_argument("--agent-id", default="agent_1")
        if model_required:
            p.add_argument("--model", required=True)
        else:
            p.add_argument("--harness", default="unspecified")
            p.add_argument("--model", default="unspecified")

    def _execution_timeouts(p):
        p.add_argument("--execution-timeout", type=float, default=300.0,
                       help="Default timeout for each submitted Python block")
        p.add_argument("--maximum-execution-timeout", type=float, default=1800.0,
                       help="Hard upper bound for a harness-requested Python timeout")
        p.add_argument("--resume", default=None,
                       help="Checkpoint ID to resume (default: latest when checkpoints exist)")

    create = sub.add_parser("create", help="Create an immutable campaign manifest")
    _campaign_identity(create)
    create.set_defaults(func=cmd_create)

    status = sub.add_parser("status", help="Show campaign state and checkpoint lineage")
    status.add_argument("--campaign", required=True)
    status.set_defaults(func=cmd_status)

    prejoin = sub.add_parser("prejoin", help="Compare campaign server mods with the desktop client")
    prejoin.add_argument("--campaign", required=True)
    prejoin.add_argument("--client-mod-dir", help="Client mods directory (default: detected)")
    prejoin.add_argument("--json", action="store_true", help="Emit the comparison as JSON")
    prejoin.set_defaults(func=cmd_prejoin)

    watch = sub.add_parser("watch", help="Wake a read-only Codex operator on campaign events")
    watch.add_argument("--campaign", required=True)
    watch.add_argument("--model", default=None, help="Operator model (default: Codex CLI's)")
    watch.add_argument("--codex-bin", default="codex")
    watch.add_argument(
        "--objective",
        default=(
            "Monitor lifecycle health and evidence-backed progress without "
            "steering the campaign or deciding its evaluation verdict."
        ),
    )
    watch.add_argument("--min-interval", type=float, default=15.0)
    watch.add_argument("--max-silence", type=float, default=300.0)
    watch.add_argument("--debounce", type=float, default=1.0)
    watch.add_argument("--inference-grace", type=float, default=15.0)
    watch.add_argument("--execution-grace", type=float, default=15.0)
    watch.add_argument("--app-server-timeout", type=float, default=30.0)
    watch.add_argument("--operator-turn-timeout", type=float, default=600.0)
    watch.add_argument("--once", action="store_true", help="One operator decision, then exit")
    watch.add_argument("--new-thread", action="store_true", help="Start a new operator thread")
    watch.set_defaults(func=cmd_watch)

    launch = sub.add_parser("launch", help="Launch or resume a campaign and open the JSONL runtime")
    _campaign_identity(launch)
    _execution_timeouts(launch)
    launch.set_defaults(func=cmd_launch)

    codex = sub.add_parser("codex", help="Run or resume a campaign through the Codex CLI harness")
    _campaign_identity(codex, model_required=True)
    codex.add_argument("--codex-bin", default="codex")
    codex.add_argument("--max-turns", type=int, default=200)
    codex.add_argument("--checkpoint-every", type=int, default=10,
                       help="Checkpoint cadence in executed Python blocks (0 disables)")
    codex.add_argument("--codex-timeout", type=float, default=900.0,
                       help="Wall-clock timeout for each Codex turn")
    _execution_timeouts(codex)
    mission = codex.add_mutually_exclusive_group()
    mission.add_argument("--notification-debug", action="store_true",
                         help="Bounded initial-research notification mission")
    mission.add_argument("--offshore-pump-debug", action="store_true",
                         help="Bounded offshore-pump placement + fluid connection mission")
    mission.add_argument("--factory-debug", action="store_true",
                         help="Open-ended factory bootstrap mission with durable planning files")
    codex.set_defaults(func=cmd_codex)
