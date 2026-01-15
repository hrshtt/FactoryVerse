"""Test fixtures for infrastructure tests.

Provides fixtures for testing the LLM boilerplate and Jupyter runtime.
"""

import pytest
import tempfile
import os
import subprocess
import time
from pathlib import Path
from typing import Generator, List, Tuple

from FactoryVerse.agent_runtime import FactoryVerseRuntime


def cleanup_orphaned_kernels() -> List[Tuple[str, str]]:
    """Clean up any orphaned Jupyter kernels.
    
    Finds and shuts down any running Jupyter kernels that might interfere
    with tests. This is especially important if previous test runs didn't
    clean up properly.
    
    Returns:
        List of tuples (kernel_id, connection_file) that were cleaned up
    """
    cleaned = []
    
    # Check both common Jupyter runtime directories
    runtime_dirs = [
        Path.home() / ".local" / "share" / "jupyter" / "runtime",
        Path.home() / "Library" / "Jupyter" / "runtime",
    ]
    
    for runtime_dir in runtime_dirs:
        if not runtime_dir.exists():
            continue
            
        for conn_file in runtime_dir.glob("kernel-*.json"):
            try:
                from jupyter_client import KernelManager
                
                km = KernelManager(connection_file=str(conn_file))
                km.load_connection_file()
                
                if km.is_alive():
                    kernel_id = conn_file.stem.replace("kernel-", "")
                    print(f"   Cleaning up orphaned kernel: {kernel_id}")
                    try:
                        km.shutdown_kernel(now=True)
                        time.sleep(0.2)  # Brief wait for shutdown
                        cleaned.append((kernel_id, str(conn_file)))
                    except Exception as e:
                        print(f"   ⚠️  Error shutting down kernel {kernel_id}: {e}")
                        # Try to kill the process directly
                        try:
                            import json
                            with open(conn_file, 'r') as f:
                                conn_info = json.load(f)
                            # Try to find and kill the process
                            result = subprocess.run(
                                ["pgrep", "-f", f"kernel-{kernel_id}"],
                                capture_output=True,
                                text=True
                            )
                            if result.returncode == 0:
                                pids = result.stdout.strip().split('\n')
                                for pid in pids:
                                    if pid:
                                        subprocess.run(["kill", "-9", pid], check=False)
                                        print(f"   Killed process {pid}")
                        except Exception:
                            pass
                
                # Remove connection file if it exists
                if conn_file.exists():
                    conn_file.unlink(missing_ok=True)
                    
            except Exception as e:
                # If we can't load the kernel, it's likely already dead
                # Just remove the connection file
                if conn_file.exists():
                    conn_file.unlink(missing_ok=True)
    
    # Also kill any orphaned ipykernel_launcher processes
    try:
        result = subprocess.run(
            ["pgrep", "-f", "ipykernel_launcher"],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode == 0:
            pids = result.stdout.strip().split('\n')
            for pid in pids:
                if pid:
                    try:
                        subprocess.run(["kill", "-9", pid], check=False, timeout=1)
                        print(f"   Killed orphaned ipykernel process: {pid}")
                    except Exception:
                        pass
    except Exception:
        pass
    
    return cleaned


@pytest.fixture(scope="session", autouse=True)
def cleanup_kernels_before_tests():
    """Session-scoped fixture to cleanup kernels before tests start.
    
    This runs automatically before any tests in the session.
    """
    print("\n🧹 Cleaning up any orphaned Jupyter kernels...")
    cleaned = cleanup_orphaned_kernels()
    if cleaned:
        print(f"   Cleaned up {len(cleaned)} orphaned kernel(s)")
    else:
        print("   No orphaned kernels found")
    print()
    
    yield
    
    # Also cleanup after all tests complete
    print("\n🧹 Final kernel cleanup...")
    cleaned = cleanup_orphaned_kernels()
    if cleaned:
        print(f"   Cleaned up {len(cleaned)} kernel(s)")
    print()


@pytest.fixture(scope="function")
def temp_session_dir() -> Generator[Path, None, None]:
    """Create a temporary session directory for testing.
    
    Creates the session directory with snapshot subdirectories
    so the boilerplate can initialize properly.
    """
    with tempfile.TemporaryDirectory(prefix="fv_test_session_") as tmpdir:
        session_dir = Path(tmpdir)
        # Create snapshot directory structure (script-output is Factorio's output dir)
        snapshot_dir = session_dir / "script-output" / "factoryverse" / "snapshots"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        yield session_dir


@pytest.fixture(scope="function")
def temp_notebook_path(temp_session_dir: Path) -> Path:
    """Create a temporary notebook path for testing."""
    notebook_path = temp_session_dir / "test_notebook.ipynb"
    return notebook_path


@pytest.fixture(scope="function")
def jupyter_runtime(
    temp_notebook_path: Path,
    rcon,
    agent_id: str,
    temp_session_dir: Path,
) -> Generator[FactoryVerseRuntime, None, None]:
    """Create a FactoryVerseRuntime with boilerplate loaded.
    
    This fixture simulates what run_agent.py does:
    1. Creates a Jupyter kernel
    2. Sets up environment variables for boilerplate
    3. Loads boilerplate.py into the kernel
    4. Loads map database
    
    **Usage**:
    ```python
    def test_boilerplate_loaded(jupyter_runtime):
        # Boilerplate is already loaded
        result = jupyter_runtime.execute_code("print(runtime.agent_id)")
        assert agent_id in result
    ```
    """
    # Set environment variables that boilerplate.py expects
    original_env = {}
    env_vars = {
        "FV_SESSION_DIR": str(temp_session_dir),
        "FV_AGENT_ID": agent_id,
        # FV_AGENT_UDP_PORT not set - will auto-allocate
    }
    
    # Save original values and set new ones
    for key, value in env_vars.items():
        original_env[key] = os.environ.get(key)
        os.environ[key] = value
    
    try:
        # Create runtime (starts Jupyter kernel)
        runtime = FactoryVerseRuntime(notebook_path=str(temp_notebook_path))
        
        # Load boilerplate (this executes boilerplate.py in the kernel)
        runtime.setup_boilerplate()
        
        # Load map database
        runtime.load_map_database()
        
        yield runtime
        
        # Cleanup - ensure kernel is properly stopped
        try:
            runtime.stop()
        except Exception as e:
            print(f"⚠️  Error during runtime.stop(): {e}")
            # Force cleanup of any orphaned kernels
            cleanup_orphaned_kernels()
    finally:
        # Restore original environment
        for key, original_value in original_env.items():
            if original_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = original_value
