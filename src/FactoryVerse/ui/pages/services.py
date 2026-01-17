from nicegui import ui
from FactoryVerse.ui.service_manager import ServiceManager
from FactoryVerse.ui.components import create_service_card


async def create_services_content(
    service_manager: ServiceManager,
    refresh_callback,
):
    """Create the services management page content."""
    with ui.column().classes("w-full gap-6"):
        ui.label("⚡ Services").classes("section-header text-2xl font-bold")

        statuses = await service_manager.get_all_statuses()

        # Core Services
        ui.label("Core Infrastructure").classes(
            "text-lg font-semibold text-gray-300 mt-4"
        )
        for status in statuses:
            if status.id in ["client", "docker"]:
                create_service_card(status, service_manager, refresh_callback)

        # Instances
        ui.label("Factorio Instances").classes(
            "text-lg font-semibold text-gray-300 mt-6"
        )
        instances = [s for s in statuses if s.id.startswith("inst_")]
        if instances:
            for status in instances:
                create_service_card(status, service_manager, refresh_callback)
        else:
            ui.label("No instances configured").classes("text-gray-500")
