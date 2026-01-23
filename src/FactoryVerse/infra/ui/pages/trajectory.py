from typing import Dict, Union, Any, TYPE_CHECKING
from nicegui import ui
from FactoryVerse.infra.services import AgentService
from FactoryVerse.infra.session.file_manager import FileManager
from FactoryVerse.infra.session.trajectory import TurnData
from FactoryVerse.infra.ui.components import create_stat_card, render_turn

if TYPE_CHECKING:
    from FactoryVerse.infra.llm.trajectory import TrajectoryManager


async def create_trajectory_content(session_id: str, agent_service: AgentService):
    """Create the trajectory viewer content.

    Uses runtime source of truth for live sessions, file fallback for historical ones.

    Args:
        session_id: Session identifier (model/run_id format)
        agent_service: Agent service instance to check for live sessions
    """
    from FactoryVerse.infra.session.trajectory import TrajectoryReader as TrajReader

    file_mgr = FileManager()

    # Parse session_id
    parts = session_id.rsplit("/", 1)
    if len(parts) != 2:
        ui.label("Invalid session ID").classes("text-red-500")
        return

    model, run_id = parts
    session_config = file_mgr.load_metadata(model, run_id)

    if not session_config:
        ui.label(f"Session {session_id} not found").classes("text-red-500")
        return

    session_dir = file_mgr.get_session_dir(session_config)
    trajectory_path = session_dir / "trajectory.jsonl"

    # Check for live session first (runtime source of truth)
    live_session = agent_service.get_session(session_id)
    data_source: Union["TrajectoryManager", TrajReader]
    is_live = False

    if live_session is not None:
        # Use in-memory trajectory_manager from the running orchestrator
        data_source = live_session.orchestrator.trajectory_manager
        is_live = True
    elif trajectory_path.exists():
        # Fallback to file-based reader for historical/completed sessions
        data_source = TrajReader(trajectory_path)
    else:
        with ui.column().classes("w-full gap-4"):
            ui.label("No trajectory data found").classes("text-amber-500 text-lg")
            ui.label("This session may not have been migrated yet.").classes(
                "text-gray-400"
            )
        return

    with ui.column().classes("w-full gap-6"):
        with ui.row().classes("items-center gap-4"):
            ui.label(f"📊 Trajectory: {session_id}").classes(
                "section-header text-2xl font-bold"
            )
            if is_live:
                with ui.row().classes(
                    "items-center gap-2 bg-green-900/30 px-3 py-1 rounded-full border border-green-500/50"
                ):
                    ui.html('<span class="status-dot running"></span>', sanitize=False)
                    ui.label("LIVE RUNTIME VIEW").classes(
                        "text-xs font-bold text-green-400 tracking-widest"
                    )

        # Stats card
        stats_container = ui.row().classes("w-full")

        def update_stats():
            stats = data_source.get_stats()
            stats_container.clear()
            with stats_container:
                with ui.grid(columns=4).classes("w-full gap-4"):
                    create_stat_card(
                        "Turns",
                        f"{stats['total_turns']}/{stats.get('completed_turns', 0)}",
                        "repeat",
                        "primary",
                    )
                    create_stat_card(
                        "Tool Calls",
                        str(stats["total_tool_calls"]),
                        "code",
                        "secondary",
                    )
                    create_stat_card(
                        "Success Rate",
                        f"{stats['success_rate']:.1f}%",
                        "check_circle",
                        "success" if stats["success_rate"] > 90 else "warning",
                    )

                    usage = stats.get("token_usage", {})
                    total_tokens = usage.get("total_tokens", 0)
                    token_str = (
                        f"{total_tokens / 1000:.1f}k"
                        if total_tokens > 1000
                        else str(total_tokens)
                    )
                    create_stat_card("Tokens", token_str, "toll", "primary")

        update_stats()

        # Turns
        turns_container = ui.column().classes("w-full gap-4 pb-32")

        # turn_num -> {render_func, last_fingerprint}
        turn_registry: Dict[int, Dict[str, Any]] = {}

        def get_turn_fingerprint(turn: TurnData) -> str:
            return f"{len(turn.tool_calls)}-{len(turn.notifications)}-{turn.is_complete}-{bool(turn.assistant_response)}"

        @ui.refreshable
        def render_single_turn(turn_num: int, reader_source):
            turns = reader_source.build_turns()
            if turn_num in turns:
                render_turn(turns[turn_num])

        async def refresh():
            update_stats()

            turns_data = data_source.build_turns()
            new_activity = False

            for turn_num in sorted(turns_data.keys()):
                turn = turns_data[turn_num]
                fp = get_turn_fingerprint(turn)

                if turn_num not in turn_registry:
                    with turns_container:
                        render_single_turn(turn_num, data_source)
                        turn_registry[turn_num] = {
                            "renderer": render_single_turn,
                            "last_fingerprint": fp,
                        }
                    new_activity = True
                elif turn_registry[turn_num]["last_fingerprint"] != fp:
                    turn_registry[turn_num]["renderer"].refresh(turn_num, data_source)
                    turn_registry[turn_num]["last_fingerprint"] = fp
                    new_activity = True

            if new_activity:
                ui.run_javascript(
                    "window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });"
                )

        await refresh()
        ui.timer(1.0 if is_live else 5.0, refresh)
