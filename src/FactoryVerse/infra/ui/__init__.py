"""FactoryVerse UI - Web-based dashboards using NiceGUI.

The preferred entry point is `run_app` which provides the unified Control Center.
The individual modules (dashboard, agent_viewer, agent_orchestrator) are kept for
backward compatibility but are deprecated in favor of the unified app.
"""

from FactoryVerse.infra.ui.app import run_app
from FactoryVerse.infra.ui.dashboard import run_dashboard
from FactoryVerse.infra.ui.agent_viewer import run_agent_viewer
from FactoryVerse.infra.ui.agent_orchestrator import run_agent_orchestrator
from FactoryVerse.infra.ui.service_manager import ServiceManager, ServiceStatus

__all__ = [
    # Unified Control Center (preferred)
    "run_app",
    # Legacy modules (deprecated)
    "run_dashboard",
    "run_agent_viewer",
    "run_agent_orchestrator",
    # Shared utilities
    "ServiceManager",
    "ServiceStatus",
]
