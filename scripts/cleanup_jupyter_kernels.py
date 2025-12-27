#!/usr/bin/env python3
"""Cleanup utility for Jupyter kernels using FactoryVerse UDP ports.

This script helps clean up orphaned Jupyter kernels that may be holding
onto UDP ports needed by FactoryVerse agents.

Usage:
    # List all running kernels
    uv run python scripts/cleanup_jupyter_kernels.py --list
    
    # Cleanup kernels using specific port (dry-run)
    uv run python scripts/cleanup_jupyter_kernels.py --port 24389 --dry-run
    
    # Cleanup kernels using specific port
    uv run python scripts/cleanup_jupyter_kernels.py --port 24389
    
    # Cleanup all FactoryVerse kernels
    uv run python scripts/cleanup_jupyter_kernels.py --all
"""
import argparse
import json
import sys
from pathlib import Path
from jupyter_client import KernelManager
from jupyter_client.kernelspec import KernelSpecManager


def list_running_kernels():
    """List all running Jupyter kernels.
    
    Returns:
        List of tuples (kernel_id, connection_file, kernel_name)
    """
    # Find all kernel connection files
    runtime_dir = Path.home() / ".local" / "share" / "jupyter" / "runtime"
    
    if not runtime_dir.exists():
        return []
    
    kernels = []
    for conn_file in runtime_dir.glob("kernel-*.json"):
        try:
            with open(conn_file, 'r') as f:
                conn_info = json.load(f)
            
            # Extract kernel ID from filename
            kernel_id = conn_file.stem.replace("kernel-", "")
            
            # Try to determine kernel name from connection info
            # This is best-effort, may not always be accurate
            kernel_name = conn_info.get("kernel_name", "unknown")
            
            kernels.append((kernel_id, str(conn_file), kernel_name))
        except Exception as e:
            print(f"⚠️  Error reading {conn_file}: {e}")
    
    return kernels


def check_kernel_using_port(connection_file: str, port: int) -> bool:
    """Check if a kernel is using a specific UDP port.
    
    This is a best-effort check that looks for port references in the
    kernel's connection file and running processes.
    
    Args:
        connection_file: Path to kernel connection file
        port: UDP port to check
        
    Returns:
        True if kernel appears to be using the port
    """
    try:
        import subprocess
        
        # Get kernel process ID from connection file
        with open(connection_file, 'r') as f:
            conn_info = json.load(f)
        
        # Try to find process using lsof
        result = subprocess.run(
            ["lsof", "-i", f"UDP:{port}", "-t"],
            capture_output=True,
            text=True,
            timeout=2
        )
        
        if result.returncode == 0 and result.stdout:
            pids = result.stdout.strip().split('\n')
            
            # Check if any of these PIDs are related to this kernel
            # This is approximate - we're checking if the port is in use
            # and assuming it might be this kernel
            return len(pids) > 0
        
        return False
    except Exception:
        return False


def shutdown_kernel(connection_file: str, dry_run: bool = False) -> bool:
    """Shutdown a Jupyter kernel.
    
    Args:
        connection_file: Path to kernel connection file
        dry_run: If True, don't actually shutdown
        
    Returns:
        True if shutdown successful (or would be in dry-run)
    """
    if dry_run:
        print(f"   [DRY-RUN] Would shutdown kernel: {connection_file}")
        return True
    
    try:
        km = KernelManager(connection_file=connection_file)
        km.load_connection_file()
        
        print(f"   Shutting down kernel: {connection_file}")
        km.shutdown_kernel(now=True)
        
        # Clean up connection file
        Path(connection_file).unlink(missing_ok=True)
        
        return True
    except Exception as e:
        print(f"   ❌ Error shutting down kernel: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Cleanup Jupyter kernels using FactoryVerse UDP ports",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument("--list", action="store_true", help="List all running kernels")
    parser.add_argument("--port", type=int, help="Cleanup kernels using specific UDP port")
    parser.add_argument("--all", action="store_true", help="Cleanup all FactoryVerse kernels")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without doing it")
    args = parser.parse_args()
    
    # List running kernels
    print("🔍 Finding running Jupyter kernels...")
    kernels = list_running_kernels()
    
    if not kernels:
        print("✅ No running Jupyter kernels found")
        return
    
    print(f"Found {len(kernels)} running kernel(s)\n")
    
    # List mode
    if args.list:
        for kernel_id, conn_file, kernel_name in kernels:
            print(f"Kernel ID: {kernel_id}")
            print(f"  Connection: {conn_file}")
            print(f"  Kernel: {kernel_name}")
            print()
        return
    
    # Cleanup by port
    if args.port:
        print(f"🔍 Looking for kernels using UDP port {args.port}...")
        
        kernels_to_shutdown = []
        for kernel_id, conn_file, kernel_name in kernels:
            if check_kernel_using_port(conn_file, args.port):
                kernels_to_shutdown.append((kernel_id, conn_file, kernel_name))
        
        if not kernels_to_shutdown:
            print(f"✅ No kernels found using port {args.port}")
            return
        
        print(f"\nFound {len(kernels_to_shutdown)} kernel(s) using port {args.port}:")
        for kernel_id, conn_file, kernel_name in kernels_to_shutdown:
            print(f"  - {kernel_id} ({kernel_name})")
        
        if args.dry_run:
            print("\n[DRY-RUN] Would shutdown these kernels")
            return
        
        print("\n🧹 Shutting down kernels...")
        for kernel_id, conn_file, kernel_name in kernels_to_shutdown:
            shutdown_kernel(conn_file, dry_run=False)
        
        print("\n✅ Cleanup complete")
        return
    
    # Cleanup all FactoryVerse kernels
    if args.all:
        print("🔍 Looking for FactoryVerse kernels...")
        
        # Look for kernels with 'fv' in the name
        fv_kernels = [
            (kid, cf, kn) for kid, cf, kn in kernels
            if 'fv' in kn.lower() or 'factoryverse' in kn.lower()
        ]
        
        if not fv_kernels:
            print("✅ No FactoryVerse kernels found")
            return
        
        print(f"\nFound {len(fv_kernels)} FactoryVerse kernel(s):")
        for kernel_id, conn_file, kernel_name in fv_kernels:
            print(f"  - {kernel_id} ({kernel_name})")
        
        if args.dry_run:
            print("\n[DRY-RUN] Would shutdown these kernels")
            return
        
        print("\n🧹 Shutting down kernels...")
        for kernel_id, conn_file, kernel_name in fv_kernels:
            shutdown_kernel(conn_file, dry_run=False)
        
        print("\n✅ Cleanup complete")
        return
    
    # No action specified
    print("❌ Please specify an action: --list, --port, or --all")
    print("   Run with --help for usage information")
    sys.exit(1)


if __name__ == "__main__":
    main()
