#!/usr/bin/env python3
"""
FactoryVerse CLI

Unified command-line interface for:
- Docker cluster management (Factorio servers + PostgreSQL + Jupyter)
- Experiment lifecycle (create, checkpoint, restore)
- Agent management
"""

import argparse
import sys
from pathlib import Path

from .infra.docker.docker_manager import ClusterManager
from .infra.experiments import ExperimentManager, ExperimentConfig


def cmd_cluster_start(args):
    """Start the FactoryVerse cluster (PostgreSQL + Jupyter + optionally Factorio)."""
    manager = ClusterManager()

    # Start with 0 Factorio instances by default (just PostgreSQL + Jupyter)
    # Users add Factorio via 'experiment create'
    num_instances = getattr(args, 'num_instances', 0)
    scenario = getattr(args, 'scenario', 'factorio_verse')

    manager.start(
        num_instances=num_instances,
        scenario=scenario,
        attach_mod=True  # Always attach mod directory
    )


def cmd_cluster_stop(args):
    """Stop the FactoryVerse cluster."""
    manager = ClusterManager()
    manager.stop()


def cmd_cluster_status(args):
    """Show cluster status."""
    manager = ClusterManager()
    manager.show()


def cmd_experiment_create(args):
    """Create a new experiment."""
    manager = ExperimentManager(
        pg_dsn=args.pg_dsn,
        notebooks_dir=Path(args.notebooks_dir),
        jupyter_url=args.jupyter_url
    )

    config = ExperimentConfig(
        agent_id=args.agent_id,
        scenario=args.scenario,
        mode=args.mode,
        checkpoint_id=args.checkpoint_id
    )

    print(f"Creating experiment for agent '{args.agent_id}'...")

    experiment = manager.create_experiment(config)

    print(f"Experiment created!")
    print(f"  Experiment ID: {experiment.experiment_id}")
    print(f"  Agent ID: {experiment.agent_id}")
    print(f"  Notebook: {experiment.notebook_path}")
    print(f"  Factorio RCON: localhost:{experiment.server_rcon_port}")
    print(f"  Factorio Game: localhost:{experiment.server_game_port}")
    print()
    print(f"Open notebook at: http://localhost:8888/notebooks/work/{Path(experiment.notebook_path).name}")


def cmd_experiment_list(args):
    """List experiments."""
    manager = ExperimentManager(
        pg_dsn=args.pg_dsn,
        notebooks_dir=Path(args.notebooks_dir),
        jupyter_url=args.jupyter_url
    )

    experiments = manager.list_experiments(status=args.status)

    if not experiments:
        print("No experiments found.")
        return

    print(f"Experiments ({len(experiments)}):")
    print()
    print(f"{'Agent ID':<20} {'Status':<12} {'Tick':<10} {'Experiment ID'}")
    print("-" * 80)

    for exp in experiments:
        print(f"{exp.agent_id:<20} {exp.status:<12} {exp.current_tick:<10} {exp.experiment_id}")


def cmd_experiment_checkpoint(args):
    """Save a checkpoint for an experiment."""
    manager = ExperimentManager(
        pg_dsn=args.pg_dsn,
        notebooks_dir=Path(args.notebooks_dir),
        jupyter_url=args.jupyter_url
    )

    print(f"Saving checkpoint for experiment {args.experiment_id}...")

    checkpoint_id = manager.save_checkpoint(
        experiment_id=args.experiment_id,
        checkpoint_type=args.type,
        description=args.description
    )

    print(f"Checkpoint saved: {checkpoint_id}")


def cmd_experiment_stop(args):
    """Stop (pause) an experiment."""
    manager = ExperimentManager(
        pg_dsn=args.pg_dsn,
        notebooks_dir=Path(args.notebooks_dir),
        jupyter_url=args.jupyter_url
    )

    print(f"Stopping experiment {args.experiment_id}...")
    manager.stop_experiment(args.experiment_id)
    print("Experiment paused.")


def cmd_factorio_start(args):
    """Start Factorio servers (legacy ClusterManager)."""
    manager = ClusterManager()

    manager.start(
        num_instances=args.num_instances,
        scenario=args.scenario,
        attach_mod=args.attach_mod,
        save_file=args.save_file
    )


def cmd_factorio_stop(args):
    """Stop Factorio servers."""
    manager = ClusterManager()
    manager.stop()


def cmd_factorio_restart(args):
    """Restart Factorio servers."""
    manager = ClusterManager()
    manager.restart()


def cmd_factorio_logs(args):
    """Show Factorio server logs."""
    manager = ClusterManager()
    manager.logs(service=args.service)


def cmd_factorio_show(args):
    """Show running Factorio containers."""
    manager = ClusterManager()
    manager.show()


def main():
    parser = argparse.ArgumentParser(
        description="FactoryVerse: LLM-powered Factorio agent platform",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    # Global options
    parser.add_argument(
        "--pg-dsn",
        default="postgresql://factoryverse:factoryverse@localhost:5432/factoryverse",
        help="PostgreSQL connection string"
    )
    parser.add_argument(
        "--notebooks-dir",
        default="./notebooks",
        help="Directory for agent notebooks"
    )
    parser.add_argument(
        "--jupyter-url",
        default="http://localhost:8888",
        help="Jupyter server URL"
    )

    subparsers = parser.add_subparsers(dest="command", help="Command")

    # ========================================================================
    # Cluster commands (docker-compose management)
    # ========================================================================
    cluster_parser = subparsers.add_parser("cluster", help="Manage FactoryVerse cluster")
    cluster_subparsers = cluster_parser.add_subparsers(dest="cluster_command")

    # cluster start
    cluster_start_parser = cluster_subparsers.add_parser("start", help="Start cluster (PostgreSQL + Jupyter + Factorio)")
    cluster_start_parser.add_argument("--num-instances", type=int, default=0, help="Number of Factorio servers (default: 0)")
    cluster_start_parser.add_argument("--scenario", default="factorio_verse", help="Factorio scenario")
    cluster_start_parser.set_defaults(func=cmd_cluster_start)

    # cluster stop
    cluster_stop_parser = cluster_subparsers.add_parser("stop", help="Stop cluster")
    cluster_stop_parser.set_defaults(func=cmd_cluster_stop)

    # cluster status
    cluster_status_parser = cluster_subparsers.add_parser("status", help="Show cluster status")
    cluster_status_parser.set_defaults(func=cmd_cluster_status)

    # ========================================================================
    # Experiment commands
    # ========================================================================
    exp_parser = subparsers.add_parser("experiment", help="Manage experiments")
    exp_subparsers = exp_parser.add_subparsers(dest="experiment_command")

    # experiment create
    exp_create_parser = exp_subparsers.add_parser("create", help="Create new experiment")
    exp_create_parser.add_argument("agent_id", help="Agent identifier")
    exp_create_parser.add_argument("--scenario", default="factorio_verse", help="Scenario name")
    exp_create_parser.add_argument("--mode", default="scenario", choices=["scenario", "save-based"], help="Game mode")
    exp_create_parser.add_argument("--checkpoint-id", help="Restore from checkpoint")
    exp_create_parser.set_defaults(func=cmd_experiment_create)

    # experiment list
    exp_list_parser = exp_subparsers.add_parser("list", help="List experiments")
    exp_list_parser.add_argument("--status", choices=["running", "paused", "completed", "failed"], help="Filter by status")
    exp_list_parser.set_defaults(func=cmd_experiment_list)

    # experiment checkpoint
    exp_checkpoint_parser = exp_subparsers.add_parser("checkpoint", help="Save checkpoint")
    exp_checkpoint_parser.add_argument("experiment_id", help="Experiment ID")
    exp_checkpoint_parser.add_argument("--type", default="manual", choices=["manual", "auto", "milestone"], help="Checkpoint type")
    exp_checkpoint_parser.add_argument("--description", help="Checkpoint description")
    exp_checkpoint_parser.set_defaults(func=cmd_experiment_checkpoint)

    # experiment stop
    exp_stop_parser = exp_subparsers.add_parser("stop", help="Stop (pause) experiment")
    exp_stop_parser.add_argument("experiment_id", help="Experiment ID")
    exp_stop_parser.set_defaults(func=cmd_experiment_stop)

    # ========================================================================
    # Factorio commands (legacy ClusterManager)
    # ========================================================================
    factorio_parser = subparsers.add_parser("factorio", help="Manage Factorio servers (legacy)")
    factorio_subparsers = factorio_parser.add_subparsers(dest="factorio_command")

    # factorio start
    factorio_start_parser = factorio_subparsers.add_parser("start", help="Start Factorio servers")
    factorio_start_parser.add_argument("--num-instances", type=int, default=1, help="Number of instances")
    factorio_start_parser.add_argument("--scenario", default="factorio_verse", help="Scenario name")
    factorio_start_parser.add_argument("--attach-mod", action="store_true", help="Attach mods directory")
    factorio_start_parser.add_argument("--save-file", help="Load from save file")
    factorio_start_parser.set_defaults(func=cmd_factorio_start)

    # factorio stop
    factorio_stop_parser = factorio_subparsers.add_parser("stop", help="Stop Factorio servers")
    factorio_stop_parser.set_defaults(func=cmd_factorio_stop)

    # factorio restart
    factorio_restart_parser = factorio_subparsers.add_parser("restart", help="Restart Factorio servers")
    factorio_restart_parser.set_defaults(func=cmd_factorio_restart)

    # factorio logs
    factorio_logs_parser = factorio_subparsers.add_parser("logs", help="Show Factorio logs")
    factorio_logs_parser.add_argument("--service", default="factorio_0", help="Service name")
    factorio_logs_parser.set_defaults(func=cmd_factorio_logs)

    # factorio show
    factorio_show_parser = factorio_subparsers.add_parser("show", help="Show running containers")
    factorio_show_parser.set_defaults(func=cmd_factorio_show)

    # ========================================================================
    # Parse and execute
    # ========================================================================
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
        sys.exit(1)


if __name__ == "__main__":
    main()
