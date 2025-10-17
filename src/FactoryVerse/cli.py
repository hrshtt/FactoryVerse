#!/usr/bin/env python3
"""
FactoryVerse CLI

Unified command-line interface for:
- Platform management (PostgreSQL + Jupyter)
- Experiment lifecycle (Factorio servers + databases + notebooks)
- Checkpoint management (save/load stubs)
- Database operations (debugging/analysis)
"""

import argparse
import sys
from pathlib import Path

from .infra.experiments import ExperimentManager
from .infra.experiments.checkpoints import CheckpointManager


def cmd_platform_start(args):
    """Start the FactoryVerse platform (PostgreSQL + Jupyter)."""
    manager = ExperimentManager(
        state_dir=Path(args.state_dir) if args.state_dir else None,
        work_dir=Path(args.work_dir) if args.work_dir else None
    )
    
    if manager.is_platform_running():
        print("Platform services are already running.")
        return
    
    manager.start_platform()


def cmd_platform_stop(args):
    """Stop the FactoryVerse platform."""
    manager = ExperimentManager(
        state_dir=Path(args.state_dir) if args.state_dir else None,
        work_dir=Path(args.work_dir) if args.work_dir else None
    )
    
    if not manager.is_platform_running():
        print("Platform services are not running.")
        return
    
    manager.stop_platform()


def cmd_platform_status(args):
    """Show platform status."""
    manager = ExperimentManager(
        state_dir=Path(args.state_dir) if args.state_dir else None,
        work_dir=Path(args.work_dir) if args.work_dir else None
    )
    
    if manager.is_platform_running():
        print("✅ Platform services are running")
        print("  📊 PostgreSQL: localhost:5432")
        print("  📓 Jupyter: http://localhost:8888")
    else:
        print("❌ Platform services are not running")
        print("  Run 'factoryverse platform start' to start services")


def cmd_experiment_create(args):
    """Create a new experiment."""
    manager = ExperimentManager(
        state_dir=Path(args.state_dir) if args.state_dir else None,
        work_dir=Path(args.work_dir) if args.work_dir else None
    )
    
    # Check if platform is running, prompt to start if not
    if not manager.is_platform_running():
        response = input("Platform services not running. Start now? [Y/n]: ")
        if response.lower() in ['', 'y', 'yes']:
            manager.start_platform()
        else:
            print("Cannot create experiment without platform services.")
            sys.exit(1)
    
    # Parse agent names
    agent_names = args.agents.split(',') if args.agents else ['agent_0']
    agent_names = [name.strip() for name in agent_names]
    
    print(f"Creating experiment '{args.name}' with {len(agent_names)} agent(s)...")
    
    try:
        exp_info = manager.create_experiment(
            experiment_name=args.name,
            scenario=args.scenario,
            agent_names=agent_names
        )
        
        print(f"\n✅ Experiment created successfully!")
        print(f"  Experiment ID: {exp_info.experiment_id}")
        print(f"  Factorio Instance: {exp_info.factorio_instance_id}")
        print(f"  Database: {exp_info.database_name}")
        print(f"  RCON Port: {exp_info.rcon_port}")
        print(f"  Game Port: {exp_info.game_port}")
        print(f"  Scenario: {exp_info.scenario}")
        print(f"\n  Agents:")
        for agent in exp_info.agents:
            print(f"    - {agent.agent_name}: {agent.notebook_path}")
        
        print(f"\n  Next steps:")
        print(f"    1. Open Jupyter: http://localhost:8888")
        print(f"    2. Open notebook: {Path(exp_info.agents[0].notebook_path).name}")
        print(f"    3. Connect to Factorio: localhost:{exp_info.rcon_port}")
        
    except Exception as e:
        print(f"❌ Failed to create experiment: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def cmd_experiment_list(args):
    """List experiments."""
    manager = ExperimentManager(
        state_dir=Path(args.state_dir) if args.state_dir else None,
        work_dir=Path(args.work_dir) if args.work_dir else None
    )
    
    try:
        experiments = manager.list_experiments(status=args.status)
        
        if not experiments:
            status_filter = f" with status '{args.status}'" if args.status else ""
            print(f"No experiments found{status_filter}.")
            return
        
        print(f"Experiments ({len(experiments)}):")
        print()
        print(f"{'Name':<20} {'Status':<10} {'Instance':<8} {'Agents':<20} {'Created'}")
        print("-" * 80)
        
        for exp in experiments:
            agent_names = ', '.join([agent.agent_name for agent in exp.agents])
            print(f"{exp.experiment_name:<20} {exp.status:<10} {exp.factorio_instance_id:<8} {agent_names:<20} {exp.created_at.strftime('%Y-%m-%d %H:%M')}")
            
    except Exception as e:
        print(f"❌ Failed to list experiments: {e}")
        sys.exit(1)


def cmd_experiment_stop(args):
    """Stop an experiment."""
    manager = ExperimentManager(
        state_dir=Path(args.state_dir) if args.state_dir else None,
        work_dir=Path(args.work_dir) if args.work_dir else None
    )
    
    try:
        exp_info = manager.get_experiment_info(args.experiment_id)
        manager.stop_experiment(args.experiment_id)
        print(f"✅ Experiment '{exp_info.experiment_name}' stopped.")
        
    except ValueError as e:
        print(f"❌ {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Failed to stop experiment: {e}")
        sys.exit(1)


def cmd_experiment_restart(args):
    """Restart an experiment."""
    manager = ExperimentManager(
        state_dir=Path(args.state_dir) if args.state_dir else None,
        work_dir=Path(args.work_dir) if args.work_dir else None
    )
    
    try:
        exp_info = manager.get_experiment_info(args.experiment_id)
        manager.restart_experiment(args.experiment_id, clean_db=args.clean_db)
        print(f"✅ Experiment '{exp_info.experiment_name}' restarted.")
        
    except ValueError as e:
        print(f"❌ {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Failed to restart experiment: {e}")
        sys.exit(1)


def cmd_experiment_info(args):
    """Show detailed information about an experiment."""
    manager = ExperimentManager(
        state_dir=Path(args.state_dir) if args.state_dir else None,
        work_dir=Path(args.work_dir) if args.work_dir else None
    )
    
    try:
        exp_info = manager.get_experiment_info(args.experiment_id)
        
        print(f"Experiment: {exp_info.experiment_name}")
        print(f"  ID: {exp_info.experiment_id}")
        print(f"  Status: {exp_info.status}")
        print(f"  Factorio Instance: {exp_info.factorio_instance_id}")
        print(f"  Database: {exp_info.database_name}")
        print(f"  Scenario: {exp_info.scenario}")
        print(f"  RCON Port: {exp_info.rcon_port}")
        print(f"  Game Port: {exp_info.game_port}")
        print(f"  Created: {exp_info.created_at}")
        print(f"  Agents ({len(exp_info.agents)}):")
        
        for agent in exp_info.agents:
            print(f"    - {agent.agent_name}")
            print(f"      Notebook: {agent.notebook_path}")
            print(f"      Status: {agent.status}")
            if agent.jupyter_kernel_id:
                print(f"      Kernel: {agent.jupyter_kernel_id}")
        
    except ValueError as e:
        print(f"❌ {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Failed to get experiment info: {e}")
        sys.exit(1)


def cmd_checkpoint_save(args):
    """Save a checkpoint for an experiment (stub)."""
    manager = ExperimentManager(
        state_dir=Path(args.state_dir) if args.state_dir else None,
        work_dir=Path(args.work_dir) if args.work_dir else None
    )
    
    checkpoint_manager = CheckpointManager(manager.pg_dsn)
    
    try:
        checkpoint_id = checkpoint_manager.save_checkpoint(
            experiment_id=args.experiment_id,
            name=args.name or f"checkpoint_{args.experiment_id}",
            metadata={"created_by": "cli"}
        )
        print(f"✅ Checkpoint saved: {checkpoint_id}")
        
    except NotImplementedError as e:
        print(f"⚠️  Checkpoint functionality not yet implemented: {e}")
    except Exception as e:
        print(f"❌ Failed to save checkpoint: {e}")
        sys.exit(1)


def cmd_checkpoint_list(args):
    """List checkpoints for an experiment."""
    manager = ExperimentManager(
        state_dir=Path(args.state_dir) if args.state_dir else None,
        work_dir=Path(args.work_dir) if args.work_dir else None
    )
    
    checkpoint_manager = CheckpointManager(manager.pg_dsn)
    
    try:
        checkpoints = checkpoint_manager.list_checkpoints(args.experiment_id)
        
        if not checkpoints:
            print(f"No checkpoints found for experiment {args.experiment_id}.")
            return
        
        print(f"Checkpoints for experiment {args.experiment_id} ({len(checkpoints)}):")
        print()
        print(f"{'ID':<36} {'Name':<20} {'Tick':<10} {'Created'}")
        print("-" * 80)
        
        for cp in checkpoints:
            print(f"{cp.checkpoint_id:<36} {cp.checkpoint_name or 'N/A':<20} {cp.game_tick:<10} {cp.created_at.strftime('%Y-%m-%d %H:%M')}")
            
    except Exception as e:
        print(f"❌ Failed to list checkpoints: {e}")
        sys.exit(1)


def cmd_checkpoint_load(args):
    """Load a checkpoint (stub)."""
    manager = ExperimentManager(
        state_dir=Path(args.state_dir) if args.state_dir else None,
        work_dir=Path(args.work_dir) if args.work_dir else None
    )
    
    checkpoint_manager = CheckpointManager(manager.pg_dsn)
    
    try:
        checkpoint_info = checkpoint_manager.load_checkpoint(args.checkpoint_id)
        print(f"✅ Checkpoint loaded: {checkpoint_info.checkpoint_name}")
        
    except NotImplementedError as e:
        print(f"⚠️  Checkpoint functionality not yet implemented: {e}")
    except Exception as e:
        print(f"❌ Failed to load checkpoint: {e}")
        sys.exit(1)


def cmd_db_query(args):
    """Execute a SQL query against an experiment's database."""
    manager = ExperimentManager(
        state_dir=Path(args.state_dir) if args.state_dir else None,
        work_dir=Path(args.work_dir) if args.work_dir else None
    )
    
    try:
        exp_info = manager.get_experiment_info(args.experiment_id)
        
        # Connect to experiment-specific database
        instance_dsn = manager.pg_dsn.replace('/postgres', f'/{exp_info.database_name}')
        
        import psycopg2
        from psycopg2.extras import RealDictCursor
        
        with psycopg2.connect(instance_dsn) as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                print(f"Executing query on experiment '{exp_info.experiment_name}' (database: {exp_info.database_name})...")
                print(f"Query: {args.query}")
                print()
                
                cur.execute(args.query)
                
                if cur.description:
                    # Query returned results
                    results = cur.fetchall()
                    
                    if results:
                        # Print column headers
                        columns = [desc[0] for desc in cur.description]
                        print(" | ".join(columns))
                        print("-" * (len(" | ".join(columns))))
                        
                        # Print rows
                        for row in results:
                            values = [str(row[col]) for col in columns]
                            print(" | ".join(values))
                        
                        print(f"\n{len(results)} rows returned.")
                    else:
                        print("No rows returned.")
                else:
                    # Query didn't return results
                    print("Query executed successfully.")
        
    except ValueError as e:
        print(f"❌ {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Failed to execute query: {e}")
        sys.exit(1)


def cmd_db_reload(args):
    """Reload database snapshots for an experiment."""
    manager = ExperimentManager(
        state_dir=Path(args.state_dir) if args.state_dir else None,
        work_dir=Path(args.work_dir) if args.work_dir else None
    )
    
    try:
        exp_info = manager.get_experiment_info(args.experiment_id)
        manager._reload_database_snapshots(exp_info.factorio_instance_id)
        print(f"✅ Database snapshots reloaded for experiment '{exp_info.experiment_name}'.")
        
    except ValueError as e:
        print(f"❌ {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Failed to reload database: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="FactoryVerse: LLM-powered Factorio agent platform",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Start platform services
  factoryverse platform start

  # Create an experiment with default agent
  factoryverse experiment create my-experiment

  # Create an experiment with multiple agents
  factoryverse experiment create my-experiment --agents agent1,agent2,agent3

  # List experiments
  factoryverse experiment list

  # Stop an experiment
  factoryverse experiment stop <experiment-id>

  # Query experiment database
  factoryverse db query <experiment-id> "SELECT * FROM map_entities LIMIT 5"

  # Reload database snapshots
  factoryverse db reload <experiment-id>
        """
    )

    # Global options
    parser.add_argument(
        "--state-dir",
        help="Directory for Docker state files (default: platform-specific)"
    )
    parser.add_argument(
        "--work-dir",
        help="Working directory for notebooks and data (default: current directory)"
    )

    subparsers = parser.add_subparsers(dest="command", help="Command")

    # ========================================================================
    # Platform commands
    # ========================================================================
    platform_parser = subparsers.add_parser("platform", help="Manage platform services")
    platform_subparsers = platform_parser.add_subparsers(dest="platform_command")

    # platform start
    platform_start_parser = platform_subparsers.add_parser("start", help="Start platform services (PostgreSQL + Jupyter)")
    platform_start_parser.set_defaults(func=cmd_platform_start)

    # platform stop
    platform_stop_parser = platform_subparsers.add_parser("stop", help="Stop platform services")
    platform_stop_parser.set_defaults(func=cmd_platform_stop)

    # platform status
    platform_status_parser = platform_subparsers.add_parser("status", help="Show platform status")
    platform_status_parser.set_defaults(func=cmd_platform_status)

    # ========================================================================
    # Experiment commands
    # ========================================================================
    exp_parser = subparsers.add_parser("experiment", help="Manage experiments")
    exp_subparsers = exp_parser.add_subparsers(dest="experiment_command")

    # experiment create
    exp_create_parser = exp_subparsers.add_parser("create", help="Create new experiment")
    exp_create_parser.add_argument("name", help="Experiment name")
    exp_create_parser.add_argument("--scenario", default="factorio_verse", help="Factorio scenario")
    exp_create_parser.add_argument("--agents", help="Comma-separated list of agent names (default: agent_0)")
    exp_create_parser.set_defaults(func=cmd_experiment_create)

    # experiment list
    exp_list_parser = exp_subparsers.add_parser("list", help="List experiments")
    exp_list_parser.add_argument("--status", choices=["running", "paused", "completed", "failed"], help="Filter by status")
    exp_list_parser.set_defaults(func=cmd_experiment_list)

    # experiment stop
    exp_stop_parser = exp_subparsers.add_parser("stop", help="Stop experiment")
    exp_stop_parser.add_argument("experiment_id", help="Experiment ID")
    exp_stop_parser.set_defaults(func=cmd_experiment_stop)

    # experiment restart
    exp_restart_parser = exp_subparsers.add_parser("restart", help="Restart experiment")
    exp_restart_parser.add_argument("experiment_id", help="Experiment ID")
    exp_restart_parser.add_argument("--clean-db", action="store_true", help="Reload database snapshots")
    exp_restart_parser.set_defaults(func=cmd_experiment_restart)

    # experiment info
    exp_info_parser = exp_subparsers.add_parser("info", help="Show experiment details")
    exp_info_parser.add_argument("experiment_id", help="Experiment ID")
    exp_info_parser.set_defaults(func=cmd_experiment_info)

    # ========================================================================
    # Checkpoint commands (stubs)
    # ========================================================================
    checkpoint_parser = subparsers.add_parser("checkpoint", help="Manage checkpoints (stub implementation)")
    checkpoint_subparsers = checkpoint_parser.add_subparsers(dest="checkpoint_command")

    # checkpoint save
    checkpoint_save_parser = checkpoint_subparsers.add_parser("save", help="Save checkpoint")
    checkpoint_save_parser.add_argument("experiment_id", help="Experiment ID")
    checkpoint_save_parser.add_argument("--name", help="Checkpoint name")
    checkpoint_save_parser.set_defaults(func=cmd_checkpoint_save)

    # checkpoint list
    checkpoint_list_parser = checkpoint_subparsers.add_parser("list", help="List checkpoints")
    checkpoint_list_parser.add_argument("experiment_id", help="Experiment ID")
    checkpoint_list_parser.set_defaults(func=cmd_checkpoint_list)

    # checkpoint load
    checkpoint_load_parser = checkpoint_subparsers.add_parser("load", help="Load checkpoint")
    checkpoint_load_parser.add_argument("checkpoint_id", help="Checkpoint ID")
    checkpoint_load_parser.set_defaults(func=cmd_checkpoint_load)

    # ========================================================================
    # Database commands
    # ========================================================================
    db_parser = subparsers.add_parser("db", help="Database operations")
    db_subparsers = db_parser.add_subparsers(dest="db_command")

    # db query
    db_query_parser = db_subparsers.add_parser("query", help="Execute SQL query")
    db_query_parser.add_argument("experiment_id", help="Experiment ID")
    db_query_parser.add_argument("query", help="SQL query to execute")
    db_query_parser.set_defaults(func=cmd_db_query)

    # db reload
    db_reload_parser = db_subparsers.add_parser("reload", help="Reload database snapshots")
    db_reload_parser.add_argument("experiment_id", help="Experiment ID")
    db_reload_parser.set_defaults(func=cmd_db_reload)

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
        import traceback
        print(f"Error: {e}", file=sys.stderr)
        print("\nFull traceback:", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()