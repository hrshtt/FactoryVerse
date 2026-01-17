import asyncio
from typing import Dict, List, Optional
from nicegui import ui
from concurrent.futures import ThreadPoolExecutor

from FactoryVerse.ui.service_manager import ServiceManager
from FactoryVerse.infra.services import AgentService
from FactoryVerse.ui.components import create_preflight_card, create_session_card


async def create_agents_content(
    service_manager: ServiceManager,
    agent_service: AgentService,
    refresh_callback,
    active_executors: List,
    shutdown_flag: Dict,
):
    """Create the agent orchestration page content."""
    with ui.column().classes("w-full gap-6"):
        ui.label("🤖 Agent Sessions").classes("section-header text-2xl font-bold")

        # Pre-flight check section
        statuses = await service_manager.get_all_statuses()
        preflight_ok = create_preflight_card(statuses)
        if not preflight_ok:
            ui.notify("Some services are not running", type="warning")

        # New session form
        with ui.card().classes("glass-card w-full p-6 mt-4"):
            ui.label("🚀 Launch New Session").classes(
                "section-header text-xl font-bold mb-4"
            )

            # Model select with dynamic loading - use dict to hold reference
            model_state: Dict[str, ui.select] = {}
            model_loading = ui.spinner(size="sm")
            model_loading.set_visibility(False)

            async def fetch_models() -> List[str]:
                """Fetch available models from Prime Intellect API."""
                import os
                from dotenv import load_dotenv

                load_dotenv()

                api_key = os.getenv("PRIME_API_KEY") or os.getenv(
                    "PRIME_INTELLECT_API_KEY"
                )
                if not api_key:
                    return []

                try:
                    from openai import OpenAI

                    client = OpenAI(
                        api_key=api_key, base_url="https://api.pinference.ai/api/v1"
                    )
                    models_resp = client.models.list()
                    return [m.id for m in models_resp.data]
                except Exception:
                    return []

            async def refresh_models():
                if "select" not in model_state:
                    return
                model_loading.set_visibility(True)
                models = await fetch_models()
                model_loading.set_visibility(False)

                sel = model_state["select"]
                if models:
                    sel.set_options(models)
                    sel.value = models[0]
                else:
                    sel.set_options(["(Enter manually)"])
                    sel.value = "(Enter manually)"
                    ui.notify(
                        "Could not fetch models. Check PRIME_API_KEY.", type="warning"
                    )

            with ui.row().classes("w-full items-end gap-2"):
                model_state["select"] = ui.select(
                    options=["Loading..."],
                    label="Model",
                    value="Loading...",
                ).classes("flex-1")

                ui.button(icon="refresh", on_click=refresh_models).props(
                    "flat dense"
                ).tooltip("Refresh models")

            # Trigger initial load
            ui.timer(0.1, refresh_models, once=True)

            with ui.grid(columns=2).classes("w-full gap-4 mt-2"):
                mode_select = ui.select(
                    ["assisted", "autonomous"], label="Mode", value="assisted"
                ).classes("w-full")

                agent_id_input = ui.input(label="Agent ID", value="agent_1").classes(
                    "w-full"
                )

            # Instance select with dynamic loading
            instance_state: Dict[str, ui.select] = {}
            instance_loading = ui.spinner(size="sm")
            instance_loading.set_visibility(False)

            def fetch_instances() -> List[str]:
                """Fetch active (running) Factorio instances."""
                from FactoryVerse.infra.instance_manager import FactorioInstanceManager

                try:
                    # Only get instances that are actually running (respond to RCON)
                    instances = FactorioInstanceManager.list_active()
                    # Return list with auto-detect option first
                    instance_names = ["(auto-detect)"] + [
                        inst.name for inst in instances
                    ]
                    return instance_names
                except Exception:
                    return ["(auto-detect)"]

            async def refresh_instances():
                if "select" not in instance_state:
                    return
                instance_loading.set_visibility(True)
                # Run in executor since list_available may do I/O
                import asyncio

                loop = asyncio.get_event_loop()
                instances = await loop.run_in_executor(None, fetch_instances)
                instance_loading.set_visibility(False)

                sel = instance_state["select"]
                sel.set_options(instances)
                sel.value = instances[0] if instances else "(auto-detect)"

            with ui.row().classes("w-full items-end gap-2"):
                instance_state["select"] = ui.select(
                    options=["(auto-detect)"],
                    label="Instance",
                    value="(auto-detect)",
                ).classes("flex-1")

                ui.button(icon="refresh", on_click=refresh_instances).props(
                    "flat dense"
                ).tooltip("Refresh instances")

            # Trigger initial load
            ui.timer(0.1, refresh_instances, once=True)

            async def start_session():
                model = model_state["select"].value if "select" in model_state else ""
                if not model or model in ["Loading...", "(Enter manually)"]:
                    ui.notify("Please select a model", type="negative")
                    return

                # Get instance value, convert "(auto-detect)" to None
                instance_val = (
                    instance_state["select"].value
                    if "select" in instance_state
                    else "(auto-detect)"
                )
                instance = None if instance_val == "(auto-detect)" else instance_val
                mode = mode_select.value

                ui.notify(f"Starting {mode} session with {model}...", type="info")

                try:
                    session = await agent_service.create_session(
                        model=model,
                        mode=mode,
                        instance=instance,
                        agent_id=agent_id_input.value.strip() or "agent_1",
                    )
                    ui.notify(f"Session created: {session.session_id}", type="positive")

                    # For autonomous mode, start a background task to run turns
                    if mode == "autonomous":
                        import asyncio
                        from concurrent.futures import ThreadPoolExecutor

                        def run_autonomous_sync():
                            """Run autonomous agent in a separate thread (blocking operations)."""
                            import asyncio

                            # Create new event loop for this thread
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)

                            turn = 0
                            try:
                                while (
                                    session.orchestrator.has_turns_remaining()
                                    and not shutdown_flag.get("stop", False)
                                ):
                                    turn += 1

                                    if turn == 1:
                                        user_msg = "You are now in control. Analyze the initial state and begin working towards automation goals. Start by exploring your surroundings and gathering resources."
                                    else:
                                        user_msg = "Continue with your current objective. You can change goals if you've completed your current task or if circumstances require adaptation."

                                    try:
                                        # Run the async run_turn in this thread's event loop
                                        loop.run_until_complete(
                                            agent_service.run_turn(
                                                session.session_id, user_msg
                                            )
                                        )
                                        print(
                                            f"[Agent {session.session_id}] Turn {turn} complete"
                                        )
                                    except Exception as e:
                                        print(
                                            f"[Agent {session.session_id}] Error in turn {turn}: {e}"
                                        )
                                        break

                                print(
                                    f"[Agent {session.session_id}] Autonomous run complete: {turn} turns"
                                )
                            except Exception as e:
                                print(f"[Agent {session.session_id}] Loop error: {e}")
                            finally:
                                # Mark session complete
                                try:
                                    session.lifecycle.complete(total_turns=turn)
                                except Exception:
                                    pass
                                loop.close()

                        # Run in thread pool executor (doesn't block NiceGUI event loop)
                        executor = ThreadPoolExecutor(
                            max_workers=1, thread_name_prefix="agent"
                        )
                        active_executors.append(executor)  # Track for cleanup
                        asyncio.get_event_loop().run_in_executor(
                            executor, run_autonomous_sync
                        )
                        ui.notify(
                            "Autonomous agent started! Refresh page to see progress. Check terminal for live output.",
                            type="info",
                        )
                    else:
                        # Assisted mode - need CLI or chat interface
                        ui.notify(
                            "Assisted mode: Use CLI 'fv agent' to interact, or view trajectory",
                            type="warning",
                        )

                    # Refresh the page to show new session
                    ui.navigate.reload()
                except Exception as e:
                    ui.notify(f"Error: {e}", type="negative")

            with ui.row().classes("w-full justify-end mt-4"):
                ui.button(
                    "LAUNCH SESSION", icon="rocket_launch", on_click=start_session
                ).props("rounded").classes("gradient-btn text-white px-6 py-2")

        # Sessions list
        ui.label("📋 All Sessions").classes("section-header text-xl font-bold mt-6")

        sessions = agent_service.list_sessions(limit=None)

        if sessions:
            for sc in sessions:
                session_id = f"{sc.model}/{sc.run_id}"
                status = agent_service.get_session_status(session_id)
                create_session_card(
                    sc,
                    status,
                    agent_service,
                    refresh_callback,
                    lambda sid: ui.navigate.to(f"/trajectory/{sid}"),
                )
        else:
            ui.label("No sessions found").classes("text-gray-500")
