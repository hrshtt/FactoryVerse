#!/usr/bin/env python3
"""FactoryVerse Status Dashboard - Real-time orchestration UI."""

from typing import List, Dict

from nicegui import ui

from FactoryVerse.ui.service_manager import ServiceManager, ServiceStatus


def create_status_card(
    status: ServiceStatus, manager: ServiceManager, refresh_callback
):
    """Create a status card for a service."""
    # Glassmorphism/Premium look using Quasar classes
    with (
        ui.card()
        .classes("w-full q-pa-md q-ma-sm shadow-2 overflow-hidden")
        .style("border-left: 5px solid " + ("#4caf50" if status.running else "#9e9e9e"))
    ):
        with ui.row().classes("w-full items-center justify-between"):
            # Status indicator + name
            with ui.row().classes("items-center gap-3"):
                ui.icon(
                    "settings" if "inst_" not in status.id else "dns",
                    color="primary" if status.running else "grey",
                ).classes("text-3xl")
                with ui.column().classes("gap-0"):
                    ui.label(status.name).classes("text-xl font-bold")
                    ui.label(status.status_text).classes(
                        "text-sm text-gray-400 font-mono"
                    )

            # Action Buttons
            with ui.row().classes("items-center gap-2"):
                if "start" in status.actions:

                    async def do_start():
                        ui.notify(f"Starting {status.name}...", type="info")
                        if status.id == "client":
                            await manager.start_client()
                        elif status.id == "docker":
                            await manager.start_docker()
                        refresh_callback()

                    ui.button("START", icon="play_arrow", on_click=do_start).props(
                        "rounded elevated color=positive"
                    )

                if "stop" in status.actions:

                    async def do_stop():
                        ui.notify(f"Stopping {status.name}...", type="warning")
                        if status.id == "client":
                            await manager.stop_client()
                        elif status.id == "docker":
                            await manager.stop_docker()
                        refresh_callback()

                    ui.button("STOP", icon="stop", on_click=do_stop).props(
                        "rounded elevated color=negative"
                    )

                if "setup" in status.actions:
                    ui.button(
                        "SETUP",
                        icon="build",
                        on_click=lambda: ui.notify(
                            "Setup not implemented in UI yet, use CLI", type="info"
                        ),
                    ).props("rounded outline color=primary")

        # Details
        if status.details:
            with ui.expansion("Service Details", icon="info_outline").classes(
                "w-full mt-3"
            ):
                with ui.column().classes("p-2 bg-gray-900 rounded"):
                    for key, value in status.details.items():
                        with ui.row().classes(
                            "w-full justify-between border-b border-gray-800 py-1"
                        ):
                            ui.label(key).classes("text-xs text-gray-500 uppercase")
                            ui.label(str(value)).classes("text-sm font-mono")


def run_dashboard(host: str = "127.0.0.1", port: int = 8080, native: bool = False):
    """Run the dashboard server."""
    manager = ServiceManager()

    @ui.page("/")
    async def main_page():
        ui.dark_mode(True)
        # Custom CSS for gradients
        ui.add_head_html("""
            <style>
                .q-header { background: linear-gradient(145deg, #1a237e 0%, #0d47a1 100%) !important; }
                .main-container { background: #121212; min-height: 100vh; }
                .service-group-label { border-left: 3px solid #2196f3; padding-left: 10px; margin-bottom: 10px; }
            </style>
        """)

        with ui.header().classes("elevated"):
            with ui.row().classes("w-full items-center q-pa-sm"):
                ui.icon("precision_manufacturing", size="md")
                ui.label("FACTORYVERSE").classes("text-2xl font-black letter-spacing-1")
                ui.badge("v0.6.0").props("outline")
                ui.space()
                with ui.row().classes("items-center gap-4"):
                    ui.label("System Status").classes("text-xs uppercase text-blue-200")
                    refresh_spinner = ui.spinner(size="sm")
                    refresh_spinner.set_visibility(False)
                    ui.button(
                        icon="refresh", on_click=lambda: ui.navigate.reload()
                    ).props("flat round text-color=white")

        with ui.column().classes("w-full max-w-5xl mx-auto p-6 gap-6 main-container"):
            status_container = ui.column().classes("w-full gap-4")

            async def refresh_status():
                refresh_spinner.set_visibility(True)
                statuses = await manager.get_all_statuses()
                status_container.clear()

                with status_container:
                    # Core Services
                    ui.label("CORE SERVICES").classes(
                        "text-sm font-bold service-group-label text-blue-400 mt-4"
                    )
                    for s in [st for st in statuses if st.id in ["client", "docker"]]:
                        create_status_card(s, manager, refresh_status)

                    # Instances
                    ui.label("FACTORIO INSTANCES").classes(
                        "text-sm font-bold service-group-label text-blue-400 mt-6"
                    )
                    for s in [st for st in statuses if st.id.startswith("inst_")]:
                        create_status_card(s, manager, refresh_status)

                refresh_spinner.set_visibility(False)

            # Initial load
            await refresh_status()

            # Auto-refresh timer
            ui.timer(5.0, refresh_status)

    ui.run(
        host=host,
        port=port,
        title="FactoryVerse Orchestrator",
        native=native,
        reload=False,
        show=True,
    )


if __name__ == "__main__":
    run_dashboard()
