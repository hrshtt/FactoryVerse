from nicegui import ui
from FactoryVerse.infra.ui.service_manager import ServiceManager
from FactoryVerse.infra.services import AgentService
from FactoryVerse.infra.session import SessionStatus
from FactoryVerse.infra.ui.components import create_stat_card, create_session_card


async def create_overview_content(
    service_manager: ServiceManager,
    agent_service: AgentService,
):
    """Create the overview/dashboard page content."""
    with ui.column().classes("w-full gap-6"):
        # Header stats
        ui.label("📊 System Overview").classes("section-header text-2xl font-bold")

        statuses = await service_manager.get_all_statuses()
        sessions = agent_service.list_sessions(limit=50)

        running_services = sum(1 for s in statuses if s.running)
        total_services = len(statuses)
        running_sessions = sum(
            1
            for sc in sessions
            if agent_service.get_session_status(f"{sc.model}/{sc.run_id}")
            == SessionStatus.RUNNING
        )
        total_sessions = len(sessions)

        with ui.grid(columns=4).classes("w-full gap-4"):
            create_stat_card(
                "Services",
                f"{running_services}/{total_services}",
                "cloud_done",
                "success",
            )
            create_stat_card(
                "Active Sessions", str(running_sessions), "smart_toy", "primary"
            )
            create_stat_card(
                "Total Sessions", str(total_sessions), "folder", "secondary"
            )
            create_stat_card(
                "System",
                "Healthy" if running_services == total_services else "Degraded",
                "health_and_safety",
                "success" if running_services == total_services else "warning",
            )

        # Quick actions
        ui.label("⚡ Quick Actions").classes(
            "section-header text-xl font-semibold mt-4"
        )

        with ui.row().classes("gap-4"):
            ui.button(
                "Start Docker",
                icon="play_arrow",
                on_click=lambda: service_manager.start_docker(),
            ).props("rounded color=positive")
            ui.button(
                "Start Client",
                icon="play_arrow",
                on_click=lambda: service_manager.start_client(),
            ).props("rounded color=positive")
            ui.button(
                "New Session", icon="add", on_click=lambda: ui.navigate.to("/agents")
            ).props("rounded color=primary")

        # Recent sessions
        ui.label("🕐 Recent Sessions").classes(
            "section-header text-xl font-semibold mt-4"
        )

        recent = sessions[:5]
        if recent:
            for sc in recent:
                session_id = f"{sc.model}/{sc.run_id}"
                status = agent_service.get_session_status(session_id)
                create_session_card(
                    sc,
                    status,
                    agent_service,
                    lambda: ui.navigate.reload(),
                    lambda sid: ui.navigate.to(f"/trajectory/{sid}"),
                )
        else:
            ui.label("No sessions yet. Start a new agent session!").classes(
                "text-gray-500"
            )
