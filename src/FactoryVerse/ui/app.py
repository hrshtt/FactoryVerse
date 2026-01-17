#!/usr/bin/env python3
"""FactoryVerse Control Center - Unified Web UI."""

import os
import signal
import atexit
from typing import List, Dict
from concurrent.futures import ThreadPoolExecutor
from nicegui import ui, app

from FactoryVerse.ui.service_manager import ServiceManager
from FactoryVerse.infra.services import AgentService
from FactoryVerse.ui.theme import apply_theme
from FactoryVerse.ui.components import create_sidebar
from FactoryVerse.ui.pages import (
    create_overview_content,
    create_services_content,
    create_agents_content,
    create_trajectory_content,
)

# Register static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.add_static_files("/static", static_dir)


def run_app(host: str = "127.0.0.1", port: int = 8080, native: bool = False):
    """Run the unified FactoryVerse Control Center."""

    service_manager = ServiceManager()
    agent_service = AgentService()

    # Track running agent executors for cleanup
    active_executors: List[ThreadPoolExecutor] = []
    shutdown_flag = {"stop": False}  # Mutable flag for threads to check

    def cleanup_sessions():
        """Cleanup all active sessions on exit."""
        shutdown_flag["stop"] = True

        for executor in active_executors:
            try:
                executor.shutdown(wait=False, cancel_futures=True)
            except Exception as e:
                print(f"   Error shutting down executor: {e}")
        active_executors.clear()

        if agent_service._sessions:
            print(
                f"\n🧹 Cleaning up {len(agent_service._sessions)} active session(s)..."
            )
            for session_id in list(agent_service._sessions.keys()):
                try:
                    session = agent_service._sessions.get(session_id)
                    if session:
                        session.lifecycle.complete(total_turns=session.turn_number)
                        print(f"   Marked {session_id} as complete")
                except Exception as e:
                    print(f"   Error cleaning up {session_id}: {e}")

    atexit.register(cleanup_sessions)

    def signal_handler(signum, frame):
        cleanup_sessions()
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    @ui.page("/")
    async def overview_page():
        apply_theme()
        with ui.row().classes("w-full h-screen"):
            create_sidebar("overview")
            with ui.column().classes("flex-1 p-8 overflow-y-auto"):
                await create_overview_content(service_manager, agent_service)

    @ui.page("/services")
    async def services_page():
        apply_theme()

        async def refresh():
            ui.navigate.reload()

        with ui.row().classes("w-full h-screen"):
            create_sidebar("services")
            with ui.column().classes("flex-1 p-8 overflow-y-auto"):
                await create_services_content(service_manager, refresh)

    @ui.page("/agents")
    async def agents_page():
        apply_theme()

        async def refresh():
            ui.navigate.reload()

        with ui.row().classes("w-full h-screen"):
            create_sidebar("agents")
            with ui.column().classes("flex-1 p-8 overflow-y-auto"):
                await create_agents_content(
                    service_manager,
                    agent_service,
                    refresh,
                    active_executors,
                    shutdown_flag,
                )

    @ui.page("/trajectory/{session_id:path}")
    async def trajectory_page(session_id: str):
        apply_theme()
        with ui.row().classes("w-full h-screen"):
            create_sidebar("agents")
            with ui.column().classes("flex-1 p-8 overflow-y-auto"):
                with ui.row().classes("items-center gap-4 mb-6"):
                    ui.button(
                        icon="arrow_back", on_click=lambda: ui.navigate.to("/agents")
                    ).props("flat round")
                    ui.label("Back to Sessions").classes("text-gray-400")
                await create_trajectory_content(session_id, agent_service)

    @ui.page("/settings")
    async def settings_page():
        apply_theme()
        with ui.row().classes("w-full h-screen"):
            create_sidebar("settings")
            with ui.column().classes("flex-1 p-8 overflow-y-auto"):
                ui.label("⚙️ Settings").classes("section-header text-2xl font-bold")
                ui.label("Settings page coming soon...").classes("text-gray-500 mt-4")

    ui.run(
        host=host,
        port=port,
        title="FactoryVerse Control Center",
        native=native,
        reload=False,
        show=True,
    )


if __name__ == "__main__":
    run_app()
