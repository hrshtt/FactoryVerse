"""Agent Orchestrator UI - Manage agent sessions from the web UI."""

import asyncio
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime
from dataclasses import dataclass

from nicegui import ui

from FactoryVerse.infra.services import AgentService, AgentSession
from FactoryVerse.infra.session import SessionStatus, TrajectoryReader
from FactoryVerse.infra.session.file_manager import SessionConfig
from FactoryVerse.infra.ui.agent_viewer import render_turn, render_tool_call


@dataclass
class ParsedSessionData:
    """Parsed session data for efficient filtering and sorting."""
    config: SessionConfig
    provider: str
    model: str
    parsed_date: Optional[datetime]
    status: Optional[SessionStatus]


def create_session_card(
    session_config: SessionConfig,
    status: Optional[SessionStatus],
    agent_service: AgentService,
    refresh_callback,
):
    """Create a card for an agent session."""
    is_running = status == SessionStatus.RUNNING
    is_complete = status == SessionStatus.COMPLETE
    is_orphaned = status == SessionStatus.ORPHANED

    # Status color
    if is_running:
        border_color = "#4caf50"  # Green
        status_text = "🟢 Running"
    elif is_complete:
        border_color = "#2196f3"  # Blue
        status_text = "✅ Complete"
    elif is_orphaned:
        border_color = "#ff9800"  # Orange
        status_text = "⚠️ Orphaned"
    else:
        border_color = "#9e9e9e"  # Grey
        status_text = "❓ Unknown"

    with (
        ui.card()
        .classes("w-full q-pa-md q-ma-sm shadow-2 overflow-hidden")
        .style(f"border-left: 5px solid {border_color}")
    ):
        with ui.row().classes("w-full items-center justify-between"):
            # Session info
            with ui.column().classes("gap-1 flex-1"):
                ui.label(f"{session_config.model}/{session_config.run_id}").classes(
                    "text-lg font-bold"
                )
                ui.label(status_text).classes("text-sm text-gray-400")
                with ui.row().classes("gap-4 text-xs text-gray-500 mt-1"):
                    ui.label(f"Mode: {session_config.mode}")
                    ui.label(f"Turns: {session_config.total_turns}")
                    if session_config.started_at:
                        started = datetime.fromisoformat(session_config.started_at)
                        ui.label(f"Started: {started.strftime('%H:%M:%S')}")

            # Actions
            with ui.row().classes("items-center gap-2"):
                if is_running:

                    async def do_stop():
                        session_id = f"{session_config.model}/{session_config.run_id}"
                        ui.notify(f"Stopping session {session_id}...", type="info")
                        try:
                            await agent_service.stop_session(session_id)
                            ui.notify("Session stopped", type="positive")
                        except Exception as e:
                            ui.notify(f"Error stopping session: {e}", type="negative")
                        refresh_callback()

                    ui.button("STOP", icon="stop", on_click=do_stop).props(
                        "rounded elevated color=negative dense"
                    )

                # View trajectory button
                session_id = f"{session_config.model}/{session_config.run_id}"

                def open_viewer():
                    # Navigate to trajectory viewer page in same app
                    session_id = f"{session_config.model}/{session_config.run_id}"
                    # Check if trajectory exists first
                    from FactoryVerse.infra.session.file_manager import FileManager
                    file_mgr = FileManager()
                    paths = file_mgr.get_session_paths(session_config)
                    trajectory_path = paths.session_dir / "trajectory.jsonl"
                    
                    if trajectory_path.exists():
                        ui.navigate.to(f"/trajectory/{session_id}")
                    else:
                        ui.notify(
                            "No trajectory data available for this session. It may not have been migrated yet.",
                            type="warning",
                        )

                ui.button("VIEW", icon="visibility", on_click=open_viewer).props(
                    "rounded outline color=primary dense"
                )


def run_agent_orchestrator(
    host: str = "127.0.0.1", port: int = 8082, native: bool = False
):
    """Run the agent orchestrator UI."""
    agent_service = AgentService()

    # Trajectory viewer page
    @ui.page("/trajectory/{session_id:path}")
    async def trajectory_page(session_id: str):
        """View trajectory for a specific session."""
        from FactoryVerse.infra.session.trajectory import TrajectoryReader
        from FactoryVerse.infra.session.file_manager import FileManager

        ui.dark_mode(True)

        # Parse session_id (format: "model/run_id" where model may contain slashes)
        # Split from right - last part is run_id, everything before is model
        parts = session_id.rsplit("/", 1)
        if len(parts) != 2:
            with ui.column().classes("w-full max-w-4xl mx-auto p-4"):
                ui.label("Invalid session ID").classes("text-red-500")
                ui.button("Back", on_click=lambda: ui.navigate.to("/")).props(
                    "rounded"
                )
            return

        model, run_id = parts
        file_mgr = FileManager()
        session_config = file_mgr.load_metadata(model, run_id)

        if not session_config:
            with ui.column().classes("w-full max-w-4xl mx-auto p-4"):
                ui.label(f"Session {session_id} not found").classes("text-red-500")
                ui.button("Back", on_click=lambda: ui.navigate.to("/")).props(
                    "rounded"
                )
            return

        # Get trajectory path
        session_dir = file_mgr.get_session_dir(session_config)
        trajectory_path = session_dir / "trajectory.jsonl"

        if not trajectory_path.exists():
            with ui.column().classes("w-full max-w-4xl mx-auto p-4 gap-4"):
                ui.label("No trajectory data found for this session").classes(
                    "text-yellow-500 text-lg"
                )
                ui.label(
                    "This session may not have been migrated to the new trajectory format yet."
                ).classes("text-gray-400")
                ui.label(f"Session directory: {session_dir}").classes(
                    "text-xs text-gray-500 font-mono"
                )
                ui.button("Back", on_click=lambda: ui.navigate.to("/")).props(
                    "rounded"
                )
            return

        # Create reader
        reader = TrajectoryReader(trajectory_path)

        with ui.header().classes("bg-indigo-900"):
            with ui.row().classes("w-full items-center gap-4 p-2"):
                ui.button(
                    icon="arrow_back", on_click=lambda: ui.navigate.to("/")
                ).props("flat round text-color=white")
                ui.icon("smart_toy", size="md")
                ui.label(f"Trajectory: {session_id}").classes("text-xl font-bold")
                ui.space()

        with ui.column().classes("w-full max-w-4xl mx-auto p-4 gap-4"):
            # Statistics
            with ui.card().classes("w-full"):
                ui.label("📊 Statistics").classes("font-bold text-lg mb-2")
                with ui.grid(columns=4).classes("w-full gap-4"):
                    with ui.column().classes("items-center"):
                        ui.label("Total/Completed").classes("text-xs text-gray-400")
                        turns_label = ui.label("0/0").classes("text-xl font-bold")

                    with ui.column().classes("items-center"):
                        ui.label("Tool Calls").classes("text-xs text-gray-400")
                        calls_label = ui.label("0").classes("text-xl font-bold")

                    with ui.column().classes("items-center"):
                        ui.label("Success Rate").classes("text-xs text-gray-400")
                        success_label = ui.label("100%").classes(
                            "text-xl font-bold text-green-400"
                        )

                    with ui.column().classes("items-center"):
                        ui.label("Token Usage").classes("text-xs text-gray-400")
                        tokens_label = ui.label("0").classes("text-xl font-bold")

            # Turns container
            turns_container = ui.column().classes("w-full gap-4")
            tool_expansions: List[ui.expansion] = []

            rendered_turns: Dict[int, bool] = {}

            async def refresh():
                stats = reader.get_stats()
                turns = reader.build_turns()

                # Update stats
                turns_label.text = (
                    f"{stats['total_turns']} / {stats.get('completed_turns', 0)}"
                )
                calls_label.text = str(stats["total_tool_calls"])
                success_rate = stats["success_rate"]
                success_label.text = f"{success_rate:.1f}%"
                success_label.classes(
                    "text-green-400" if success_rate > 90 else "text-red-400",
                    remove="text-green-400 text-red-400",
                )

                usage = stats.get("token_usage", {})
                total_tokens = usage.get("total_tokens", 0)
                if total_tokens > 1000:
                    tokens_label.text = f"{total_tokens / 1000:.1f}k"
                else:
                    tokens_label.text = str(total_tokens)

                # Render new turns
                for turn_num in sorted(turns.keys()):
                    if turn_num not in rendered_turns:
                        turn = turns[turn_num]
                        with turns_container:
                            render_turn(turn, tool_expansions)
                        rendered_turns[turn_num] = True

            await refresh()
            ui.timer(2.0, refresh)

    @ui.page("/")
    async def main_page():
        ui.dark_mode(True)
        ui.add_head_html("""
            <style>
                .q-header { background: linear-gradient(145deg, #1a237e 0%, #0d47a1 100%) !important; }
                .main-container { background: #121212; min-height: 100vh; }
                .section-label { border-left: 3px solid #2196f3; padding-left: 10px; margin-bottom: 10px; }
            </style>
        """)

        with ui.header().classes("elevated"):
            with ui.row().classes("w-full items-center q-pa-sm"):
                ui.icon("smart_toy", size="md")
                ui.label("AGENT ORCHESTRATOR").classes(
                    "text-2xl font-black letter-spacing-1"
                )
                ui.badge("v0.6.0").props("outline")
                ui.space()
                with ui.row().classes("items-center gap-4"):
                    ui.label("Agent Sessions").classes("text-xs uppercase text-blue-200")
                    refresh_spinner = ui.spinner(size="sm")
                    refresh_spinner.set_visibility(False)
                    ui.button(
                        icon="refresh", on_click=lambda: ui.navigate.reload()
                    ).props("flat round text-color=white")

        with ui.column().classes("w-full max-w-6xl mx-auto p-6 gap-6 main-container"):
            # New Session Section
            with ui.card().classes("w-full"):
                ui.label("🚀 New Agent Session").classes(
                    "text-lg font-bold mb-4 section-label"
                )

                model_input = ui.input(
                    label="Model", placeholder="intellect-3, gpt-4o, etc."
                ).classes("w-full")
                mode_select = ui.select(
                    ["assisted", "autonomous"],
                    label="Mode",
                    value="assisted",
                ).classes("w-full")
                instance_input = ui.input(
                    label="Instance (optional)", placeholder="client, server_0, etc."
                ).classes("w-full")
                agent_id_input = ui.input(
                    label="Agent ID", value="agent_1"
                ).classes("w-full")
                max_turns_input = ui.number(
                    label="Max Turns (optional)", value=None, format="%d"
                ).classes("w-full")

                async def start_session():
                    model = model_input.value.strip()
                    if not model:
                        ui.notify("Model name is required", type="negative")
                        return

                    mode = mode_select.value
                    instance = instance_input.value.strip() or None
                    agent_id = agent_id_input.value.strip() or "agent_1"
                    max_turns = (
                        int(max_turns_input.value) if max_turns_input.value else None
                    )

                    ui.notify(f"Starting {mode} session with {model}...", type="info")

                    try:
                        session = await agent_service.create_session(
                            model=model,
                            mode=mode,
                            instance=instance,
                            agent_id=agent_id,
                            max_turns=max_turns,
                        )
                        ui.notify(
                            f"Session started: {session.session_id}", type="positive"
                        )
                        # Clear inputs
                        model_input.value = ""
                        instance_input.value = ""
                        # Refresh list
                        await refresh_sessions()
                    except Exception as e:
                        ui.notify(f"Error starting session: {e}", type="negative")
                        import traceback

                        print(traceback.format_exc())

                ui.button(
                    "START SESSION", icon="play_arrow", on_click=start_session
                ).props("rounded elevated color=positive").classes("w-full mt-4")

            # Filter and Sort Controls
            with ui.card().classes("w-full"):
                ui.label("🔍 Filter & Sort").classes(
                    "text-lg font-bold mb-4 section-label"
                )
                
                with ui.row().classes("w-full gap-4 items-end"):
                    # Provider filter
                    provider_select = ui.select(
                        options=["All"],
                        label="Provider",
                        value="All",
                    ).classes("flex-1")
                    
                    # Model filter
                    model_select = ui.select(
                        options=["All"],
                        label="Model",
                        value="All",
                    ).classes("flex-1")
                    
                    # Sort by
                    # NiceGUI select with tuples uses the label (first element) as the value
                    sort_select = ui.select(
                        options=[
                            "Date (Newest)",
                            "Date (Oldest)",
                            "Turns (Most)",
                            "Turns (Least)",
                        ],
                        label="Sort By",
                        value="Date (Newest)",
                    ).classes("flex-1")
                
                # Toggle to filter out zero-turn sessions
                with ui.row().classes("w-full gap-4 items-center mt-2"):
                    hide_zero_turns = ui.checkbox(
                        "Hide sessions with 0 turns",
                        value=False,
                    ).classes("flex-1")
                    
                    # Auto-refresh on filter/sort change
                    # NiceGUI select uses 'update:model-value' event (Vue.js pattern)
                    provider_select.on("update:model-value", lambda: refresh_sessions())
                    model_select.on("update:model-value", lambda: refresh_sessions())
                    sort_select.on("update:model-value", lambda: refresh_sessions())
                    hide_zero_turns.on("update:model-value", lambda: refresh_sessions())

            # Sessions List
            sessions_container = ui.column().classes("w-full gap-4")
            
            # Cache for parsed session data
            parsed_sessions_cache: List[ParsedSessionData] = []

            def parse_all_sessions(sessions: List[SessionConfig]) -> List[ParsedSessionData]:
                """Parse all session metadata upfront.
                
                Returns:
                    List of ParsedSessionData with all metadata pre-computed
                """
                from FactoryVerse.infra.session.file_manager import FileManager
                file_mgr = FileManager()
                parsed = []
                
                for session_config in sessions:
                    # Extract provider and model from path
                    session_dir = file_mgr.get_session_dir(session_config)
                    rel_path = session_dir.relative_to(file_mgr.runs_dir)
                    parts = rel_path.parts
                    
                    if len(parts) == 2:
                        provider, model = "", parts[0]
                    elif len(parts) == 3:
                        provider, model = parts[0], parts[1]
                    else:
                        # Fallback: parse from model field
                        if "/" in session_config.model:
                            provider, model = session_config.model.split("/", 1)
                        else:
                            provider, model = "", session_config.model
                    
                    # Parse date from run_id
                    try:
                        parsed_date = datetime.strptime(session_config.run_id, "%Y-%m-%d_%H-%M-%S")
                    except (ValueError, TypeError):
                        parsed_date = None
                    
                    # Get status
                    session_id = f"{session_config.model}/{session_config.run_id}"
                    status = agent_service.get_session_status(session_id)
                    
                    parsed.append(ParsedSessionData(
                        config=session_config,
                        provider=provider,
                        model=model,
                        parsed_date=parsed_date,
                        status=status,
                    ))
                
                return parsed

            async def refresh_sessions():
                refresh_spinner.set_visibility(True)
                sessions_container.clear()

                # Get all sessions and parse everything upfront
                all_sessions = agent_service.list_sessions(limit=None)

                if not all_sessions:
                    with sessions_container:
                        ui.label("No sessions found").classes(
                            "text-gray-500 text-center py-8"
                        )
                    refresh_spinner.set_visibility(False)
                    parsed_sessions_cache.clear()
                    return

                # Parse all sessions once
                parsed_sessions_cache.clear()
                parsed_sessions_cache.extend(parse_all_sessions(all_sessions))

                # Extract unique providers and models from parsed data
                providers_set = set()
                models_set = set()
                
                for parsed in parsed_sessions_cache:
                    if parsed.provider:
                        providers_set.add(parsed.provider)
                    models_set.add(parsed.model)

                # Update filter dropdowns
                provider_options = ["All"] + sorted(providers_set)
                model_options = ["All"] + sorted(models_set)
                
                # Update selects (preserve current selection if still valid)
                current_provider = provider_select.value
                current_model = model_select.value
                
                provider_select.set_options(provider_options)
                model_select.set_options(model_options)
                
                # Restore selection if still valid
                if current_provider in provider_options:
                    provider_select.value = current_provider
                else:
                    provider_select.value = "All"
                    
                if current_model in model_options:
                    model_select.value = current_model
                else:
                    model_select.value = "All"

                # Apply filters using parsed data
                selected_provider = provider_select.value
                selected_model = model_select.value
                hide_zero = hide_zero_turns.value
                
                filtered_parsed = []
                for parsed in parsed_sessions_cache:
                    # Apply provider filter
                    if selected_provider != "All":
                        if parsed.provider != selected_provider:
                            continue
                    
                    # Apply model filter
                    if selected_model != "All":
                        if parsed.model != selected_model:
                            continue
                    
                    # Apply zero-turns filter
                    if hide_zero and parsed.config.total_turns == 0:
                        continue
                    
                    filtered_parsed.append(parsed)

                # Apply sorting using parsed data
                sort_label = sort_select.value
                
                def sort_key(parsed: ParsedSessionData):
                    if sort_label == "Date (Newest)":
                        return parsed.parsed_date if parsed.parsed_date else datetime.min
                    elif sort_label == "Date (Oldest)":
                        return parsed.parsed_date if parsed.parsed_date else datetime.max
                    elif sort_label == "Turns (Most)":
                        # Sort by turns descending (most first)
                        return parsed.config.total_turns
                    elif sort_label == "Turns (Least)":
                        # Sort by turns ascending (least first)
                        return parsed.config.total_turns
                    else:
                        # Default: newest first
                        return parsed.parsed_date if parsed.parsed_date else datetime.min
                
                # Determine reverse flag based on label
                # For "Turns (Most)", we want reverse=True (descending)
                # For "Turns (Least)", we want reverse=False (ascending)
                reverse = sort_label in ["Date (Newest)", "Turns (Most)"]
                filtered_parsed.sort(key=sort_key, reverse=reverse)

                with sessions_container:
                    # Organize filtered sessions by status (using pre-parsed data)
                    running_parsed = []
                    complete_parsed = []
                    orphaned_parsed = []
                    unknown_parsed = []

                    for parsed in filtered_parsed:
                        if parsed.status == SessionStatus.RUNNING:
                            running_parsed.append(parsed)
                        elif parsed.status == SessionStatus.COMPLETE:
                            complete_parsed.append(parsed)
                        elif parsed.status == SessionStatus.ORPHANED:
                            orphaned_parsed.append(parsed)
                        else:
                            unknown_parsed.append(parsed)

                    # Sort each group separately to maintain sort order within status groups
                    # (They're already sorted, but we re-sort each group to be safe)
                    running_parsed.sort(key=sort_key, reverse=reverse)
                    complete_parsed.sort(key=sort_key, reverse=reverse)
                    orphaned_parsed.sort(key=sort_key, reverse=reverse)
                    unknown_parsed.sort(key=sort_key, reverse=reverse)

                    # Show running sessions first
                    if running_parsed:
                        ui.label("🟢 RUNNING SESSIONS").classes(
                            "text-sm font-bold section-label text-green-400 mt-4"
                        )
                        for parsed in running_parsed:
                            create_session_card(
                                parsed.config, parsed.status, agent_service, refresh_sessions
                            )

                    # Show orphaned sessions
                    if orphaned_parsed:
                        ui.label("⚠️ ORPHANED SESSIONS").classes(
                            "text-sm font-bold section-label text-orange-400 mt-6"
                        )
                        for parsed in orphaned_parsed:
                            create_session_card(
                                parsed.config, parsed.status, agent_service, refresh_sessions
                            )

                    # Show all completed/old sessions
                    if complete_parsed:
                        ui.label("✅ COMPLETED SESSIONS").classes(
                            "text-sm font-bold section-label text-blue-400 mt-6"
                        )
                        ui.label(f"Showing {len(complete_parsed)} completed sessions").classes(
                            "text-xs text-gray-500 mb-2"
                        )
                        for parsed in complete_parsed:
                            create_session_card(
                                parsed.config, parsed.status, agent_service, refresh_sessions
                            )

                    # Show unknown (should be rare)
                    if unknown_parsed:
                        ui.label("❓ UNKNOWN SESSIONS").classes(
                            "text-sm font-bold section-label text-gray-400 mt-6"
                        )
                        for parsed in unknown_parsed:
                            create_session_card(
                                parsed.config, parsed.status, agent_service, refresh_sessions
                            )

                refresh_spinner.set_visibility(False)

            # Initial load
            await refresh_sessions()

            # Auto-refresh timer
            ui.timer(3.0, refresh_sessions)

    ui.run(
        host=host,
        port=port,
        title="FactoryVerse Agent Orchestrator",
        native=native,
        reload=False,
        show=True,
    )


if __name__ == "__main__":
    run_agent_orchestrator()
