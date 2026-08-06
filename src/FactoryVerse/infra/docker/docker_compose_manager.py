#!/usr/bin/env python3
"""Docker Compose orchestration for FactoryVerse."""

import subprocess
import json
from pathlib import Path
from typing import Dict
import yaml


def setup_compose_cmd():
    """Determine docker-compose command."""
    candidates = [
        ["docker", "compose"],
        ["docker-compose"],
    ]
    for cmd in candidates:
        try:
            subprocess.run(cmd + ["version"], check=True, capture_output=True)
            return cmd if isinstance(cmd, list) else ["docker-compose"]
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
    raise RuntimeError("Docker Compose not found. Install Docker Desktop.")


class DockerComposeManager:
    """Orchestrates Docker Compose file generation and lifecycle."""

    def __init__(self, work_dir: Path, compose_path: Path | None = None):
        self.work_dir = work_dir.resolve()
        self.compose_path = (
            Path(compose_path).resolve()
            if compose_path is not None
            else self.work_dir / "docker-compose.yml"
        )
        self.services: Dict[str, dict] = {}
        self.compose_cmd = setup_compose_cmd()

    def add_services(self, component: str, services: Dict[str, dict]) -> None:
        """Add services from a component."""
        self.services.update(services)
        print(f"✓ Added {len(services)} service(s) from {component}")

    def write_compose(self) -> None:
        """Generate and write docker-compose.yml."""
        if not self.services:
            raise RuntimeError("No services to write to compose file")

        # Compose Specification no longer uses the legacy top-level version
        # field; current Docker Compose warns and ignores it.
        compose_data = {"services": self.services}

        self.compose_path.write_text(yaml.dump(compose_data, sort_keys=False))
        print(f"✓ Generated docker-compose.yml ({len(self.services)} services)")

    def up(self) -> None:
        """Start all services."""
        if not self.compose_path.exists():
            raise RuntimeError(
                "docker-compose.yml not found. Call write_compose() first."
            )

        subprocess.run(
            self.compose_cmd + ["-f", str(self.compose_path), "up", "-d"], check=True
        )
        print("✅ Services started")

    def down(self) -> None:
        """Stop all services."""
        if not self.compose_path.exists():
            raise RuntimeError("docker-compose.yml not found.")

        subprocess.run(
            self.compose_cmd + ["-f", str(self.compose_path), "down"], check=True
        )
        print("✅ Services stopped")

    def restart(self) -> None:
        """Restart all services."""
        if not self.compose_path.exists():
            raise RuntimeError("docker-compose.yml not found.")

        subprocess.run(
            self.compose_cmd + ["-f", str(self.compose_path), "restart"], check=True
        )
        print("✅ Services restarted")

    def start_service(self, service_name: str) -> None:
        """Start a specific service."""
        if not self.compose_path.exists():
            raise RuntimeError("docker-compose.yml not found.")

        subprocess.run(
            self.compose_cmd + ["-f", str(self.compose_path), "start", service_name],
            check=True,
        )
        print(f"✅ Service '{service_name}' started")

    def stop_service(self, service_name: str) -> None:
        """Stop a specific service."""
        if not self.compose_path.exists():
            raise RuntimeError("docker-compose.yml not found.")

        subprocess.run(
            self.compose_cmd + ["-f", str(self.compose_path), "stop", service_name],
            check=True,
        )
        print(f"✅ Service '{service_name}' stopped")

    def restart_service(self, service_name: str) -> None:
        """Restart a specific service."""
        if not self.compose_path.exists():
            raise RuntimeError("docker-compose.yml not found.")

        subprocess.run(
            self.compose_cmd + ["-f", str(self.compose_path), "restart", service_name],
            check=True,
        )
        print(f"✅ Service '{service_name}' restarted")

    def logs(self, service: str, follow: bool = False) -> None:
        """Get logs for a service."""
        if not self.compose_path.exists():
            raise RuntimeError("docker-compose.yml not found.")

        cmd = self.compose_cmd + ["-f", str(self.compose_path), "logs"]
        if follow:
            cmd.append("-f")
        cmd.append(service)
        subprocess.run(cmd, check=True)

    def capture_logs(self, service: str | None = None) -> str:
        """Return non-streaming Compose logs for durable failure evidence."""
        if not self.compose_path.exists():
            return ""

        cmd = self.compose_cmd + [
            "-f",
            str(self.compose_path),
            "logs",
            "--no-color",
            "--timestamps",
        ]
        if service:
            cmd.append(service)
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return result.stdout + result.stderr

    def exec(self, service: str, command: str) -> str:
        """Execute command in a service."""
        if not self.compose_path.exists():
            raise RuntimeError("docker-compose.yml not found.")

        result = subprocess.run(
            self.compose_cmd
            + [
                "-f",
                str(self.compose_path),
                "exec",
                "-T",
                service,
                "sh",
                "-c",
                command,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout

    def ps(self) -> list[dict]:
        """Get status of containers."""
        if not self.compose_path.exists():
            return []

        result = subprocess.run(
            self.compose_cmd + ["-f", str(self.compose_path), "ps", "--format", "json"],
            capture_output=True,
            text=True,
            check=False,
        )
        if not result.stdout.strip():
            return []

        try:
            # Docker Compose V2 returns one JSON object per line or an array
            output = result.stdout.strip()
            if output.startswith("["):
                return json.loads(output)
            return [json.loads(line) for line in output.splitlines()]
        except Exception:
            return []

    def is_running(self) -> bool:
        """Check if any services are running."""
        containers = self.ps()
        # Filter for running state if needed, but presence usually implies some state.
        # Docker compose ps usually lists running containers by default unless -a is used,
        # but here we didn't use -a.
        return len(containers) > 0
