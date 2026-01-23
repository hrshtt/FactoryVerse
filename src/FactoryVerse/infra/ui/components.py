"""Reusable UI components for FactoryVerse."""

from typing import Dict, List, Optional, Callable
from nicegui import ui
from FactoryVerse.infra.ui.service_manager import ServiceManager, ServiceStatus
from FactoryVerse.infra.services import AgentService
from FactoryVerse.infra.session import SessionStatus
from FactoryVerse.infra.session.file_manager import SessionConfig
from FactoryVerse.infra.session.trajectory import TurnData


def create_stat_card(label: str, value: str, icon: str, color: str = "primary"):
    """Create a statistics card."""
    with ui.column().classes("stat-card items-center gap-1"):
        ui.icon(icon, size="md").classes(f"text-{color}")
        ui.label(value).classes("stat-value")
        ui.label(label).classes("text-xs text-gray-400 uppercase")


def create_status_indicator(running: bool, label: Optional[str] = None):
    """Create a status indicator dot."""
    status_class = "running" if running else "stopped"
    with ui.row().classes("items-center gap-2"):
        ui.html(f'<span class="status-dot {status_class}"></span>', sanitize=False)
        if label:
            ui.label(label).classes("text-sm")


def create_service_card(
    status: ServiceStatus,
    manager: ServiceManager,
    refresh_callback: Callable,
):
    """Create a premium service status card."""
    with ui.card().classes("glass-card w-full p-4"):
        with ui.row().classes("w-full items-center justify-between"):
            # Left side - status and name
            with ui.row().classes("items-center gap-3"):
                icon_name = "dns" if "inst_" in status.id else "settings_applications"
                ui.icon(icon_name, size="lg").classes(
                    "text-indigo-400" if status.running else "text-gray-500"
                )
                with ui.column().classes("gap-0"):
                    ui.label(status.name).classes("text-lg font-semibold")
                    create_status_indicator(status.running, status.status_text)

            # Right side - actions
            with ui.row().classes("gap-2"):
                if "start" in status.actions:

                    async def do_start(sid=status.id):
                        ui.notify(f"Starting {status.name}...", type="info")
                        if sid == "client":
                            await manager.start_client()
                        elif sid == "docker":
                            await manager.start_docker()
                        ui.navigate.reload()

                    ui.button("Start", icon="play_arrow", on_click=do_start).props(
                        "rounded color=positive dense"
                    )

                if "stop" in status.actions:

                    async def do_stop(sid=status.id):
                        ui.notify(f"Stopping {status.name}...", type="warning")
                        if sid == "client":
                            await manager.stop_client()
                        elif sid == "docker":
                            await manager.stop_docker()
                        ui.navigate.reload()

                    ui.button("Stop", icon="stop", on_click=do_stop).props(
                        "rounded color=negative dense"
                    )

        # Details expansion
        if status.details:
            with ui.expansion("Details", icon="info").classes("w-full mt-2"):
                for key, value in status.details.items():
                    with ui.row().classes("w-full justify-between py-1"):
                        ui.label(key).classes("text-xs text-gray-500 uppercase")
                        ui.label(str(value)).classes("text-sm font-mono")


def create_session_card(
    session_config: SessionConfig,
    status: Optional[SessionStatus],
    agent_service: AgentService,
    refresh_callback: Callable,
    on_view_click: Callable[[str], None],
):
    """Create a session card with premium styling."""
    status_class_map: Dict[SessionStatus, str] = {
        SessionStatus.RUNNING: "running",
        SessionStatus.COMPLETE: "complete",
        SessionStatus.ORPHANED: "orphaned",
    }
    status_class = status_class_map.get(status, "") if status else ""

    status_info_map: Dict[SessionStatus, tuple[str, str]] = {
        SessionStatus.RUNNING: ("🟢 Running", "text-green-400"),
        SessionStatus.COMPLETE: ("✅ Complete", "text-blue-400"),
        SessionStatus.ORPHANED: ("⚠️ Orphaned", "text-amber-400"),
    }
    status_info = (
        status_info_map.get(status, ("❓ Unknown", "text-gray-400"))
        if status
        else ("❓ Unknown", "text-gray-400")
    )

    with ui.card().classes(f"glass-card session-card {status_class} w-full p-4"):
        with ui.row().classes("w-full items-center justify-between"):
            # Session info
            with ui.column().classes("gap-1 flex-1"):
                ui.label(f"{session_config.model}").classes("text-lg font-semibold")
                ui.label(session_config.run_id).classes(
                    "text-xs text-gray-500 font-mono"
                )

                with ui.row().classes("gap-4 mt-1"):
                    ui.label(status_info[0]).classes(f"text-sm {status_info[1]}")
                    ui.label(f"Mode: {session_config.mode}").classes(
                        "text-xs text-gray-400"
                    )
                    ui.label(f"Turns: {session_config.total_turns}").classes(
                        "text-xs text-gray-400"
                    )

            # Actions
            with ui.row().classes("gap-2"):
                if status == SessionStatus.RUNNING:

                    async def do_stop():
                        session_id = f"{session_config.model}/{session_config.run_id}"
                        ui.notify(f"Stopping session {session_id}...", type="warning")
                        try:
                            await agent_service.stop_session(session_id)
                            ui.notify("Session stopped", type="positive")
                        except Exception as e:
                            ui.notify(f"Error: {e}", type="negative")
                        ui.navigate.reload()

                    ui.button(icon="stop", on_click=do_stop).props(
                        "rounded dense color=negative"
                    ).tooltip("Stop Session")

                def view_session():
                    session_id = f"{session_config.model}/{session_config.run_id}"
                    on_view_click(session_id)

                ui.button(icon="visibility", on_click=view_session).props(
                    "rounded dense color=primary"
                ).tooltip("View Trajectory")


def create_preflight_card(statuses: List[ServiceStatus]) -> bool:
    """Create pre-flight check card. Returns True if all checks pass."""
    all_good = all(s.running for s in statuses if s.id in ["client", "docker"])

    border_color = "border-green-500" if all_good else "border-amber-500"

    with ui.card().classes(f"preflight-card glass-card w-full p-4 {border_color}"):
        ui.label("🔍 Pre-flight Check").classes("section-header text-lg font-bold mb-3")

        with ui.column().classes("gap-2 w-full"):
            for status in statuses:
                if status.id not in ["client", "docker"] and not status.id.startswith(
                    "inst_"
                ):
                    continue

                icon = "check_circle" if status.running else "cancel"
                color = "text-green-400" if status.running else "text-red-400"

                with ui.row().classes("items-center gap-2"):
                    ui.icon(icon).classes(color)
                    ui.label(status.name).classes("text-sm")
                    ui.label(status.status_text).classes(
                        "text-xs text-gray-500 ml-auto"
                    )

        if not all_good:
            ui.label(
                "⚠️ Some services are not running. Agent session may fail."
            ).classes("text-amber-400 text-sm mt-3")

    return all_good


def render_tool_call(tool: dict) -> None:
    """Render a tool call with result."""
    is_error = tool.get("is_error", False)
    tool_name = tool.get("name", "unknown")

    with ui.expansion(
        f"{'🐍' if tool.get('language') == 'python' else '🗄️'} {tool_name}"
    ).classes("tool-expansion w-full"):
        with ui.row().classes("items-center gap-2 mb-2"):
            ui.badge(
                "ERROR" if is_error else "SUCCESS",
                color="negative" if is_error else "positive",
            )
            if tool.get("duration"):
                ui.label(f"⏱️ {tool['duration']:.2f}s").classes("text-xs text-gray-500")

        if tool.get("code"):
            ui.markdown(f"```python\n{tool['code']}\n```").classes("w-full text-xs")

        if tool.get("output"):
            with ui.scroll_area().classes("h-32 w-full bg-black/30 p-2 rounded"):
                ui.markdown(f"```text\n{tool['output']}\n```").classes("text-xs")


def render_turn(turn: "TurnData") -> None:
    """Render a single turn."""
    with ui.card().classes("glass-card w-full p-4"):
        with ui.row().classes("items-center gap-3 mb-2"):
            ui.label(f"Turn {turn.turn_number}").classes(
                "text-lg font-bold gradient-text"
            )
            ui.badge(
                "Complete" if turn.is_complete else "In Progress",
                color="positive" if turn.is_complete else "warning",
            )

        ui.separator()

        if turn.user_message:
            ui.chat_message(turn.user_message, name="User", sent=True)

        for tool in turn.tool_calls:
            render_tool_call(tool)

        for notif in turn.notifications:
            ui.chat_message(notif, name="System", avatar="📢").classes("bg-purple-900")

        if turn.assistant_response:
            ui.chat_message(turn.assistant_response, name="Assistant", avatar="🤖")


def create_sidebar(current_page: str):
    """Create the sidebar navigation."""
    nav_items = [
        ("overview", "📊 Overview", "dashboard"),
        ("services", "⚡ Services", "cloud"),
        ("agents", "🤖 Agents", "smart_toy"),
        ("settings", "⚙️ Settings", "settings"),
    ]

    with ui.column().classes("sidebar h-screen w-64 py-6 px-4 gap-2"):
        # Logo
        with ui.row().classes("items-center gap-2 px-3 mb-8"):
            ui.icon("precision_manufacturing", size="lg").classes("text-indigo-400")
            ui.label("FACTORYVERSE").classes(
                "text-xl font-black tracking-wider gradient-text"
            )

        # Navigation items
        for page_id, label, icon in nav_items:
            is_active = current_page == page_id

            with (
                ui.row()
                .classes(
                    f"sidebar-item items-center gap-3 p-3 cursor-pointer {'active' if is_active else ''}"
                )
                .on(
                    "click",
                    lambda p=page_id: ui.navigate.to(
                        f"/{p if p != 'overview' else ''}"
                    ),
                )
            ):
                ui.icon(icon).classes(
                    "text-gray-400" if not is_active else "text-indigo-400"
                )
                ui.label(label.split(" ", 1)[1]).classes(
                    "text-gray-400" if not is_active else "text-white font-semibold"
                )

        ui.space()

        # Version badge at bottom
        with ui.row().classes("items-center gap-2 px-3"):
            ui.badge("v0.7.0").props("outline")
            ui.label("Control Center").classes("text-xs text-gray-600")
