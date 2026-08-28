"""`fv campaign` — supervised freeplay campaigns (create/status/prejoin/launch).

The Codex and Hermes transports were removed 2026-08-29; external harnesses
are redeveloped after the refactor. `launch` serves the transport-agnostic
stdio actor protocol. Registered via ``register``.
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



def register(subparsers) -> None:
    """Attach `campaign` and its subcommands to the top-level parser."""
    parser = subparsers.add_parser(
        "campaign", help="Supervised freeplay campaigns (create/status/prejoin/launch)"
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

    launch = sub.add_parser("launch", help="Launch or resume a campaign and open the JSONL runtime")
    _campaign_identity(launch)
    _execution_timeouts(launch)
    launch.set_defaults(func=cmd_launch)

