#!/usr/bin/env python3
"""Jupyter service management for FactoryVerse."""

import platform
from pathlib import Path
from typing import Dict


class JupyterManager:
    """Manages Jupyter service configuration."""
    
    def __init__(self, work_dir: Path):
        self.work_dir = work_dir.resolve()
        self.arch = platform.machine()
    
    def _docker_platform(self) -> str:
        """Get Docker platform based on architecture."""
        return "linux/arm64" if self.arch in ["arm64", "aarch64"] else "linux/amd64"
    
    def get_services(self) -> Dict[str, dict]:
        """Generate Jupyter service configuration."""
        return {
            "jupyter": {
                "image": "jupyter/minimal-notebook:latest",
                "platform": self._docker_platform(),
                "environment": {
                    "JUPYTER_ENABLE_LAB": "yes",
                    "GRANT_SUDO": "yes",
                    "JUPYTER_TOKEN": "",  # Disable token for local dev
                },
                "ports": ["8888:8888/tcp"],
                "volumes": [
                    f"{(self.work_dir / 'notebooks').resolve()}:/home/jovyan/work",
                    f"{self.work_dir.resolve()}:/home/jovyan/factoryverse:ro",
                ],
                "restart": "unless-stopped",
            }
        }
