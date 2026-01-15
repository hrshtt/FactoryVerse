"""Main entry point for running FactoryVerse agents."""

import os
import sys
import asyncio
import argparse
import logging
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

from FactoryVerse.agent_runtime import FactoryVerseRuntime
from FactoryVerse.infra.llm.client import PrimeIntellectClient
from FactoryVerse.infra.llm.agent_orchestrator import FactorioAgentOrchestrator
from FactoryVerse.infra.llm.session_manager import SessionManager
from FactoryVerse.infra.llm.initial_state_generator import InitialStateGenerator
from FactoryVerse.infra.llm.console_output import ConsoleOutput
from FactoryVerse.utils.rcon_utils import validate_rcon_connection

# Configure logging - will be reconfigured per session
logger = logging.getLogger(__name__)

# Global interrupt tracking
interrupt_count = 0
should_stop = False


def get_rcon_config() -> tuple[str, int, str]:
    """Load RCON configuration using instance manager.

    Auto-detects which Factorio instance is running (client or server).
    """
    from FactoryVerse.infra.instance_manager import FactorioInstanceManager

    instance = FactorioInstanceManager.get_active(require_single=False)
    return instance.rcon_host, instance.rcon_port, instance.rcon_password


def list_available_models() -> list[str]:
    """List available models from Prime Intellect API."""
    api_key = os.getenv("PRIME_API_KEY")
    if not api_key:
        raise ValueError("PRIME_API_KEY not set in environment")

    client = OpenAI(api_key=api_key, base_url="https://api.pinference.ai/api/v1")

    models = client.models.list()
    return [model.id for model in models.data]


async def run_assisted(agent: FactorioAgentOrchestrator):
    """Run agent in assisted mode (interactive)."""
    global interrupt_count, should_stop

    print("\n🤖 Agent Online. Type 'exit' to quit.")
    print("📊 Statistics available with 'stats' command.")
    print("🔄 Reload boilerplate with '/reload_boilerplate' (add '--factorio' to also reload Factorio scripts).")
    print("🔢 Set max turns with '/set_max_turns <number>' or '/set_max_turns unlimited'.\n")

    try:
        while True:
            try:
                user_input = input("\nUser > ")

                if user_input.lower() in ["exit", "quit"]:
                    break

                if user_input.lower() == "stats":
                    stats = agent.get_statistics()
                    print(f"\n📊 Statistics:")
                    print(f"  Total actions: {stats['total_actions']}")
                    print(f"  Successful: {stats['success_count']}")
                    print(f"  Failed: {stats['failure_count']}")
                    if stats["total_actions"] > 0:
                        print(
                            f"  Success rate: {stats['success_count'] / stats['total_actions']:.1%}"
                        )
                    continue

                # Handle /reload_boilerplate command
                if user_input.lower().startswith("/reload_boilerplate"):
                    print("\n🔄 Reloading boilerplate modules...")
                    try:
                        reload_factorio = "--factorio" in user_input.lower() or "-f" in user_input.lower()
                        result = runtime.reload_boilerplate(reload_factorio=reload_factorio)
                        print("✅ Boilerplate reloaded successfully")
                        print("   Runtime objects have been recreated with updated code")
                        print("   RCON connection and UDP port preserved")
                        if reload_factorio:
                            print("   Factorio scripts have been reloaded")
                    except Exception as e:
                        print(f"❌ Failed to reload boilerplate: {e}")
                        logger.exception("Error reloading boilerplate")
                    continue

                # Handle /set_max_turns command
                if user_input.lower().startswith("/set_max_turns") or user_input.lower().startswith("/max_turns"):
                    parts = user_input.split()
                    if len(parts) < 2:
                        current = agent.max_turns if agent.max_turns else "unlimited"
                        print(f"\n📊 Current max turns: {current}")
                        print("   Usage: /set_max_turns <number> or /set_max_turns unlimited")
                        continue
                    
                    try:
                        value = parts[1].lower()
                        if value == "unlimited" or value == "none" or value == "inf":
                            agent.set_max_turns(None)
                            print(f"\n✅ Max turns set to: unlimited")
                        else:
                            max_turns = int(value)
                            if max_turns < 0:
                                print(f"\n❌ Max turns must be a non-negative integer or 'unlimited'")
                                continue
                            agent.set_max_turns(max_turns)
                            remaining = max_turns - agent.turn_number
                            print(f"\n✅ Max turns set to: {max_turns}")
                            print(f"   Current turn: {agent.turn_number}, Remaining: {remaining}")
                    except ValueError:
                        print(f"\n❌ Invalid value: '{parts[1]}'. Must be a number or 'unlimited'")
                    continue

                # Run agent turn
                response = await agent.run_turn(user_input)

                print(f"\n✅ Turn {agent.turn_number - 1} complete")
                print(f"   Agent: {response}")

            except KeyboardInterrupt:
                interrupt_count += 1
                if interrupt_count == 1:
                    print(
                        "\n\n⚠️  Interrupt received. Press Ctrl+C again to exit, or continue interacting."
                    )
                    should_stop = True
                    continue
                else:
                    print("\n\n👋 Exiting...")
                    break

    except Exception as e:
        logger.exception("Error in assisted mode")
        raise


async def run_autonomous(agent: FactorioAgentOrchestrator, max_turns: int):
    """Run agent in autonomous mode (self-directed)."""
    global interrupt_count, should_stop

    # Set initial max_turns on agent if not already set
    if agent.max_turns is None:
        agent.set_max_turns(max_turns)
    
    # Use agent's max_turns (which may have been changed via command)
    effective_max_turns = agent.max_turns
    max_turns_display = effective_max_turns if effective_max_turns is not None else "∞"
    
    print(f"\n🤖 Agent running autonomously for up to {max_turns_display} turns...")
    print("Press Ctrl+C once to pause, twice to exit.\n")

    try:
        turn = 0
        while True:
            # Check if we've reached the limit
            if not agent.has_turns_remaining():
                print(f"\n⏹️  Max turns limit reached ({agent.max_turns} turns)")
                break
            
            if should_stop:
                print("\n⏸️  Paused. Press Ctrl+C again to exit.")
                try:
                    # Wait for second interrupt or user input
                    await asyncio.sleep(1000000)  # Long sleep, interrupted by Ctrl+C
                except KeyboardInterrupt:
                    print("\n👋 Exiting...")
                    break

            try:
                # TODO: Implement autonomous turn logic
                remaining = agent.max_turns - agent.turn_number if agent.max_turns is not None else "∞"
                print(f"Turn {turn + 1}/{max_turns_display} (Remaining: {remaining})")
                await asyncio.sleep(1)  # Placeholder
                
                turn += 1

            except KeyboardInterrupt:
                interrupt_count += 1
                if interrupt_count == 1:
                    print("\n\n⚠️  Interrupt received. Pausing...")
                    should_stop = True
                    continue
                else:
                    print("\n\n👋 Exiting...")
                    break

    except Exception as e:
        logger.exception("Error in autonomous mode")
        raise


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Run FactoryVerse Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive model selection
  uv run python scripts/run_agent.py
  
  # Specify model directly
  uv run python scripts/run_agent.py --model intellect-3
  
  # List available models
  uv run python scripts/run_agent.py --list-models
  
  # List existing sessions
  uv run python scripts/run_agent.py --list-sessions
  
  # Autonomous mode (future)
  uv run python scripts/run_agent.py --autonomous --max-turns 100
        """,
    )
    parser.add_argument("--model", help="Model name (e.g., intellect-3)")
    parser.add_argument(
        "--list-models", action="store_true", help="List available models"
    )
    parser.add_argument(
        "--list-sessions", action="store_true", help="List existing sessions"
    )
    parser.add_argument(
        "--autonomous", action="store_true", help="Run in autonomous mode"
    )
    parser.add_argument("--max-turns", type=int, help="Max turns for autonomous mode")
    args = parser.parse_args()

    load_dotenv()

    # Validate RCON connection first, before doing anything else
    # Skip validation only for --list-sessions (doesn't need Factorio)
    if not args.list_sessions:
        print("\n🔍 Validating RCON connection...")
        try:
            host, port, password = get_rcon_config()
            success, error = validate_rcon_connection(host, port, password)

            if not success:
                print(f"\n❌ RCON connection failed: {error}")
                print("\n💡 Make sure Factorio is running with RCON enabled.")
                print(f"   Expected: {host}:{port}")
                sys.exit(1)

            print(f"✅ RCON connection validated ({host}:{port})")
        except Exception as e:
            print(f"\n❌ Error validating RCON connection: {e}")
            sys.exit(1)

    # List models
    if args.list_models:
        print("\n🔍 Fetching available models...")
        try:
            models = list_available_models()
            print(f"\n✅ Available models ({len(models)}):")
            for model in models:
                print(f"  - {model}")
        except Exception as e:
            print(f"❌ Error fetching models: {e}")
        return

    # List sessions
    if args.list_sessions:
        session_mgr = SessionManager()
        sessions = session_mgr.list_sessions(limit=20)
        print(f"\n📋 Recent sessions ({len(sessions)}):")
        for session in sessions:
            status = "✅" if session.ended_at else "🔄"
            print(f"  {status} {session.model}/{session.run_id}")
            print(f"     Mode: {session.mode}, Turns: {session.total_turns}")
            if session.ended_at:
                print(f"     Completed: {session.ended_at}")
        return

    # Select model
    if args.model:
        model_name = args.model
    else:
        print("🔍 Fetching available models...")
        try:
            models = list_available_models()
            print(f"\n✅ Available models:")
            for i, model in enumerate(models, 1):
                print(f"  {i}. {model}")

            while True:
                try:
                    choice = int(input("\nSelect model (number): ")) - 1
                    if 0 <= choice < len(models):
                        model_name = models[choice]
                        break
                    else:
                        print("Invalid choice, try again")
                except ValueError:
                    print("Please enter a number")
        except Exception as e:
            print(f"❌ Error fetching models: {e}")
            return

    # Create session
    session_mgr = SessionManager()
    mode = "autonomous" if args.autonomous else "assisted"
    session = session_mgr.create_session(model_name, mode)
    paths = session_mgr.get_session_paths(session)

    # Set per-agent runtime config via environment variables
    # These are read by the boilerplate to configure the agent
    os.environ["FV_SESSION_DIR"] = str(paths["session_dir"])
    os.environ["FV_AGENT_ID"] = "agent_1"  # For now, single agent
    # FV_AGENT_UDP_PORT not set - will auto-allocate from default

    # Validate UDP port availability before starting
    # This prevents runtime failures if port is already in use
    from FactoryVerse.config import FactoryVerseConfig
    from FactoryVerse.utils.port_utils import validate_udp_port, find_process_using_port

    config = FactoryVerseConfig()
    udp_port = config.agent_port_base  # Default port that will be used

    print(f"\n🔍 Validating UDP port {udp_port}...")
    success, error = validate_udp_port(udp_port)

    if not success:
        print(f"❌ UDP port validation failed: {error}")

        # Try to find what's using the port
        process_info = find_process_using_port(udp_port)
        if process_info:
            print(f"\n💡 Port is being used by:")
            print(f"   {process_info}")

        print(f"\n💡 To fix this:")
        print(
            f"   1. Run cleanup utility: uv run python scripts/cleanup_jupyter_kernels.py --port {udp_port}"
        )
        print(f"   2. Or manually kill the process using the port")
        print(
            f"   3. Or set a different port via FV_AGENT_UDP_PORT environment variable"
        )
        sys.exit(1)

    print(f"✅ UDP port {udp_port} is available")

    print(f"\n🎮 Starting {mode} session")
    print(f"🤖 Agent ID: agent_1")
    print(f"📁 Session: {paths['session_dir']}")
    print(f"💾 Database: {paths['session_dir']}/map.duckdb")
    print(f"📓 Notebook: {paths['notebook']}")

    print(f"💬 Chat log: {paths['chat_log']}")

    # Configure logging for this session
    log_file = Path(paths["session_dir"]) / "debug.log"

    # Clear any existing handlers
    root_logger = logging.getLogger()
    root_logger.handlers.clear()

    # File handler for detailed logs
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    root_logger.addHandler(file_handler)
    root_logger.setLevel(logging.INFO)

    # Suppress httpx logs on console (they'll still go to file)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    print(f"📝 Debug log: {log_file}")

    # Initialize runtime
    print("\n🚀 Initializing FactoryVerse Runtime...")
    runtime = FactoryVerseRuntime(notebook_path=str(paths["notebook"]))

    print("💉 Injecting boilerplate...")
    runtime.setup_boilerplate()

    print("📊 Loading map database...")
    runtime.load_map_database()

    # Generate initial state
    print("📋 Generating initial state summary...")
    state_gen = InitialStateGenerator(runtime)
    initial_state = state_gen.generate_summary(paths["session_dir"])
    print(f"✅ Initial state saved to: {paths['initial_state']}")

    # Initialize LLM
    print("🧠 Initializing LLM...")
    api_key = os.getenv("PRIME_API_KEY")
    if not api_key:
        raise ValueError("PRIME_API_KEY not set in environment")

    llm = PrimeIntellectClient(api_key=api_key, model=model_name)

    # Generate fresh system prompt from latest documentation
    # Consolidated prompt is ephemeral and session-specific
    print("🔧 Generating system prompt from latest documentation...")
    import subprocess

    # System prompt will be written to session directory (ephemeral)
    system_prompt_path = str(paths["session_dir"] / "system_prompt.md")

    try:
        # Step 1: Generate API documentation via introspection
        subprocess.run(
            ["uv", "run", "python", "scripts/generate_docs.py"],
            check=True,
            capture_output=True,
        )

        # Step 2: Generate schema documentation
        subprocess.run(
            ["uv", "run", "python", "scripts/generate_schema_docs.py"],
            check=True,
            capture_output=True,
        )

        # Step 3: Assemble the system prompt in session directory (without examples - they're stale)
        subprocess.run(
            ["uv", "run", "python", "scripts/assemble_prompt.py", system_prompt_path],
            check=True,
            capture_output=True,
        )

        print(f"✅ Generated fresh system prompt for this session")
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to generate system prompt: {e}")
        if e.stderr:
            print(f"   Error: {e.stderr.decode().strip()}")
        print("⚠️  System prompt generation failed - agent may not work correctly")
        # Don't set a fallback path - let the orchestrator handle the error
        system_prompt_path = None

    # Create orchestrator
    print(f"🎯 Initializing Agent Orchestrator...")
    if system_prompt_path:
        print(f"📄 System prompt: {system_prompt_path}")
    else:
        print(f"⚠️  No system prompt available - using fallback")
    console = ConsoleOutput(enabled=True)
    agent = FactorioAgentOrchestrator(
        llm_client=llm,
        runtime=runtime,
        system_prompt_path=system_prompt_path or "docs/system-prompt/factoryverse-system-prompt-v3-template.md",  # Fallback to template if generation failed
        chat_log_path=str(paths["chat_log"]),
        console_output=console,
        initial_state_path=str(paths["initial_state"]),
        mode=mode,
    )

    # Run
    try:
        try:
            if mode == "assisted":
                await run_assisted(agent)
            else:
                await run_autonomous(agent, args.max_turns or 100)
        except KeyboardInterrupt:
            # Catch any remaining keyboard interrupts during initialization
            print("\n\n⚠️  Interrupted during initialization")
    finally:
        # Save final metadata
        import datetime

        session.ended_at = datetime.datetime.now().isoformat()
        session.total_turns = agent.turn_number
        session_mgr.update_session(session)

        # Cleanup
        print("\n🧹 Cleaning up...")
        runtime.stop()
        print("✅ Done!")
        print(f"\n📁 Session saved to: {paths['session_dir']}")


if __name__ == "__main__":
    asyncio.run(main())
