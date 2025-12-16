"""Simple agent inference script."""
import os
import asyncio
import logging
from pathlib import Path
from dotenv import load_dotenv

from FactoryVerse.agent_runtime import FactoryVerseRuntime
from FactoryVerse.llm.client import PrimeIntellectClient
from FactoryVerse.llm.agent_orchestrator import FactorioAgentOrchestrator

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_next_session_path(model_name: str = "intellect-3") -> Path:
    """Get path for next session notebook."""
    gameplay_dir = Path("gameplay") / model_name
    gameplay_dir.mkdir(parents=True, exist_ok=True)
    
    # Find next session number
    existing = list(gameplay_dir.glob("session_*.ipynb"))
    if not existing:
        session_num = 1
    else:
        nums = []
        for path in existing:
            try:
                num = int(path.stem.split("_")[-1])
                nums.append(num)
            except ValueError:
                continue
        session_num = max(nums) + 1 if nums else 1
    
    return gameplay_dir / f"session_{session_num}.ipynb"


async def main():
    """Main agent loop."""
    load_dotenv()
    
    # Get model name
    model_name = os.getenv("LLM_MODEL", "intellect-3").split("/")[-1]
    
    # 1. Create runtime
    print("🚀 Initializing FactoryVerse Runtime...")
    notebook_path = get_next_session_path(model_name)
    print(f"📓 Session notebook: {notebook_path}")
    
    runtime = FactoryVerseRuntime(notebook_path=str(notebook_path))
    
    # 2. Setup boilerplate
    print("💉 Injecting boilerplate...")
    runtime.setup_boilerplate()
    
    # 3. Load map database
    print("📊 Loading map database...")
    runtime.load_map_database()
    
    # 4. Initialize LLM
    print("🧠 Initializing LLM...")
    api_key = os.getenv("PRIME_API_KEY")
    if not api_key:
        raise ValueError("PRIME_API_KEY not set in environment")
    
    llm = PrimeIntellectClient(api_key=api_key)
    
    # 5. Create orchestrator
    print("🎯 Initializing Agent Orchestrator...")
    agent = FactorioAgentOrchestrator(
        llm_client=llm,
        runtime=runtime,
        system_prompt_path="factoryverse-system-prompt.md"
    )
    
    # 6. Interactive loop
    print("\n🤖 Agent Online. Type 'exit' to quit.")
    print("📊 Statistics available with 'stats' command.\n")
    
    try:
        while True:
            user_input = input("\nUser > ")
            
            if user_input.lower() in ['exit', 'quit']:
                break
            
            if user_input.lower() == 'stats':
                stats = agent.get_statistics()
                print(f"\n📊 Statistics:")
                print(f"  Total actions: {stats['total_actions']}")
                print(f"  Successful: {stats['success_count']}")
                print(f"  Failed: {stats['failure_count']}")
                if stats['total_actions'] > 0:
                    print(f"  Success rate: {stats['success_count'] / stats['total_actions']:.1%}")
                continue
            
            # Run agent turn
            response = await agent.run_turn(user_input)
            
            print(f"\n✅ Turn {agent.turn_number - 1} complete")
            print(f"   Agent: {response}")
    
    except KeyboardInterrupt:
        print("\n\n👋 Interrupted by user")
    
    finally:
        # 7. Cleanup
        print("\n🧹 Cleaning up...")
        runtime.stop()
        print("✅ Done!")


if __name__ == "__main__":
    asyncio.run(main())
