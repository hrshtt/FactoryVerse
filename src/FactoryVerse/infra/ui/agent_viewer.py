"""Agent Trajectory Viewer - NiceGUI-based web UI for agent observation.

Supports two sources:
1. Runtime (primary): TrajectoryManager from live agent process
2. File (fallback): TrajectoryReader for replay/decoupled observation

Both sources implement the same interface: build_turns(), get_stats()
"""

from pathlib import Path
from typing import Union, Dict, Protocol, List, Optional, Any, TYPE_CHECKING
from nicegui import ui

if TYPE_CHECKING:
    from FactoryVerse.infra.llm.trajectory import TrajectoryManager
    from FactoryVerse.infra.session.trajectory import TrajectoryReader


class TrajectorySource(Protocol):
    """Protocol for trajectory data sources."""

    def build_turns(self) -> Dict[int, "TurnData"]: ...
    def get_stats(self) -> Dict[str, Any]: ...


# Import TurnData after protocol to avoid circular import
from FactoryVerse.infra.session.trajectory import TurnData


def render_tool_call(
    tool: dict, expansion_list: Optional[List[ui.expansion]] = None
) -> None:
    """Render a single tool call with code and result."""
    status_color = "negative" if tool.get("is_error") else "positive"
    icon = "🐍" if tool.get("language") == "python" else "🗄️"

    expansion = ui.expansion(
        f"{icon} {tool.get('name', 'unknown')}",
        icon="code",
    ).classes("w-full")

    if expansion_list is not None:
        expansion_list.append(expansion)

    with expansion:
        with ui.row().classes("items-center gap-2"):
            ui.badge("ERROR" if tool.get("is_error") else "SUCCESS", color=status_color)
            ui.label(f"iteration {tool.get('iteration', '?')}").classes(
                "text-xs text-gray-500"
            )

        if tool.get("code"):
            ui.code(tool["code"], language=tool.get("language", "python")).classes(
                "w-full"
            )

        if tool.get("result"):
            result_text = tool["result"]
            if len(result_text) > 500:
                result_text = result_text[:500] + "\n... (truncated)"
            with ui.card().classes("w-full bg-gray-800 p-2"):
                ui.label("Result:").classes("text-xs text-gray-400")
                ui.label(result_text).classes("font-mono text-sm whitespace-pre-wrap")


def render_turn(
    turn: TurnData, expansion_list: Optional[List[ui.expansion]] = None
) -> None:
    """Render a single turn card."""
    with ui.card().classes("w-full"):
        with ui.row().classes("items-center gap-2"):
            ui.label(f"Turn {turn.turn_number}").classes("text-lg font-bold")
            if turn.is_complete:
                ui.badge("Complete", color="positive")
            else:
                ui.badge("In Progress", color="warning")

        ui.separator()

        if turn.user_message:
            ui.chat_message(turn.user_message, name="User", sent=True).classes("w-full")

        for tool in turn.tool_calls:
            render_tool_call(tool, expansion_list)

        for notif in turn.notifications:
            ui.chat_message(notif, name="System", avatar="📢").classes(
                "w-full bg-purple-900"
            )

        if turn.assistant_response:
            ui.chat_message(
                turn.assistant_response, name="Assistant", avatar="🤖"
            ).classes("w-full")


def run_agent_viewer(
    source: Union["TrajectoryManager", "TrajectoryReader", Path, str] = None,
    host: str = "127.0.0.1",
    port: int = 8081,
):
    """Run the agent trajectory viewer.

    Args:
        source: Data source - can be:
            - TrajectoryManager: Live in-memory source (primary)
            - TrajectoryReader: File-based source
            - Path/str: Session directory path (creates TrajectoryReader)
        host: Host to bind to
        port: Port to bind to
    """
    # Resolve source
    if source is None:
        # Demo mode
        from FactoryVerse.infra.session.trajectory import (
            TrajectoryWriter,
            TrajectoryReader,
        )
        from FactoryVerse.infra.session.lifecycle import SessionLifecycle
        import tempfile

        tmpdir = tempfile.mkdtemp()
        session_dir = Path(tmpdir)
        trajectory_path = session_dir / "trajectory.jsonl"

        # Write demo data
        writer = TrajectoryWriter(trajectory_path)
        writer.session_start(model="demo", mode="assisted")
        writer.user_message("What iron patches are nearby?", turn=1)
        writer.tool_start("execute_duckdb", turn=1, iteration=1)
        writer.tool_code(
            "SELECT * FROM resource_tile WHERE name = 'iron-ore' LIMIT 5",
            turn=1,
            lang="sql",
        )
        writer.tool_result("{'name': 'iron-ore', 'amount': 1000}", turn=1, success=True)
        writer.assistant_response("I found iron ore at (10, 20) with 1000 ore.", turn=1)
        writer.turn_complete(turn=1)

        lifecycle = SessionLifecycle(session_dir)
        lifecycle.start(model="demo", mode="assisted")

        data_source = TrajectoryReader(trajectory_path)
        print(f"Demo mode: {session_dir}")

    elif isinstance(source, (str, Path)):
        # File-based
        from FactoryVerse.infra.session.trajectory import TrajectoryReader

        session_dir = Path(source)
        data_source = TrajectoryReader(session_dir / "trajectory.jsonl")

    else:
        # Runtime object (TrajectoryManager or TrajectoryReader)
        data_source = source

    @ui.page("/")
    @ui.page("/")
    async def main_page():
        ui.dark_mode(True)

        tool_expansions: List[ui.expansion] = []

        def expand_all():
            for e in tool_expansions:
                e.value = True

        def collapse_all():
            for e in tool_expansions:
                e.value = False

        with ui.header().classes("bg-indigo-900"):
            with ui.row().classes("w-full items-center gap-4 p-2"):
                ui.icon("smart_toy", size="md")
                ui.label("FACTORYVERSE AGENT VIEWER").classes("text-xl font-bold")

                ui.separator().props("vertical")

                ui.button("Expand All", on_click=expand_all, icon="unfold_more").props(
                    "flat dense"
                )
                ui.button(
                    "Collapse All", on_click=collapse_all, icon="unfold_less"
                ).props("flat dense")

                ui.space()
                turn_badge = ui.badge("Turn: 0", color="blue")
                status_badge = ui.badge("Live", color="positive")

        with ui.column().classes("w-full max-w-4xl mx-auto p-4 gap-4"):
            # Statistics Section
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
                        tokens_detail_label = ui.label("P: 0 | C: 0").classes(
                            "text-xs text-gray-500"
                        )

            turns_container = ui.column().classes("w-full gap-4")

            with ui.card().classes("w-full"):
                ui.label("📢 Notifications").classes("font-bold")
                notification_log = ui.log(max_lines=20).classes("w-full h-32")

        rendered_turns: Dict[int, bool] = {}

        async def refresh():
            stats = data_source.get_stats()

            # Update Header badges
            turn_badge.text = f"Turn: {stats.get('completed_turns', 0)}"
            status_badge.text = f"{stats['total_tool_calls']} calls"
            status_badge.props(
                f"color={'positive' if stats['errors'] == 0 else 'negative'}"
            )

            # Update Stats Section
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

            # Token Usage
            usage = stats.get("token_usage", {})
            total_tokens = usage.get("total_tokens", 0)
            p_tokens = usage.get("prompt_tokens", 0)
            c_tokens = usage.get("completion_tokens", 0)

            if total_tokens > 1000:
                tokens_label.text = f"{total_tokens / 1000:.1f}k"
            else:
                tokens_label.text = str(total_tokens)

            tokens_detail_label.text = f"P: {p_tokens} | C: {c_tokens}"

            turns = data_source.build_turns()
            for turn_num in sorted(turns.keys()):
                if turn_num not in rendered_turns:
                    turn = turns[turn_num]
                    with turns_container:
                        render_turn(turn, tool_expansions)
                    rendered_turns[turn_num] = True

                    for notif in turn.notifications:
                        ts = (
                            turn.started_at.strftime("%H:%M:%S")
                            if turn.started_at
                            else "??:??:??"
                        )
                        notification_log.push(f"[{ts}] {notif}")

        await refresh()
        ui.timer(2.0, refresh)

    ui.run(
        host=host, port=port, title="FactoryVerse Agent Viewer", reload=False, show=True
    )


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        run_agent_viewer(sys.argv[1])
    else:
        run_agent_viewer()  # Demo mode
