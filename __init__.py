"""Hermes Agentic Variation plugin registration."""

try:
    from . import schemas, tools
except ImportError:  # Pytest can collect a repository-root plugin as top-level __init__.
    import schemas
    import tools


def register(ctx):
    """Register read-only inspection plus the backend-gated single-step Phase 1 tools."""
    phase1_enabled = ctx.get_config("phase1_enabled", default=False) is True
    phase2_enabled = ctx.get_config("phase2_enabled", default=False) is True
    raw_wait = ctx.get_config("phase1_wait_seconds", default=120)
    wait_seconds = raw_wait if type(raw_wait) is int and 5 <= raw_wait <= 180 else 120
    raw_phase2_wait = ctx.get_config("phase2_wait_seconds", default=120)
    phase2_wait_seconds = (
        raw_phase2_wait
        if type(raw_phase2_wait) is int and 5 <= raw_phase2_wait <= 180
        else 120
    )
    controller_instance = None
    phase2_controller_instance = None

    def controller_factory():
        nonlocal controller_instance
        if controller_instance is None:
            from plugins.plugin_storage import plugin_data_dir

            try:
                from .controller import Phase1Controller
                from .runtime import HermesLifecycleAdapter
                from .storage import RunStore
            except ImportError:
                from controller import Phase1Controller
                from runtime import HermesLifecycleAdapter
                from storage import RunStore

            store = RunStore(plugin_data_dir("agentic-variation") / "phase1.db")
            controller_instance = Phase1Controller(
                store=store,
                lifecycle=HermesLifecycleAdapter(ctx.subagent_lifecycle),
                enabled=phase1_enabled,
                wait_seconds=wait_seconds,
            )
        return controller_instance

    def phase2_controller_factory():
        nonlocal phase2_controller_instance
        if phase2_controller_instance is None:
            from plugins.plugin_storage import plugin_data_dir

            try:
                from .phase2 import Phase2Controller
                from .runtime import HermesLifecycleAdapter
                from .storage import RunStore
            except ImportError:
                from phase2 import Phase2Controller
                from runtime import HermesLifecycleAdapter
                from storage import RunStore

            phase2_controller_instance = Phase2Controller(
                store=RunStore(plugin_data_dir("agentic-variation") / "phase1.db"),
                lifecycle=HermesLifecycleAdapter(ctx.subagent_lifecycle, phase=2),
                enabled=phase2_enabled,
                wait_seconds=phase2_wait_seconds,
            )
        return phase2_controller_instance

    phase1_handlers = tools.make_phase1_handlers(controller_factory)
    phase2_handlers = tools.make_phase2_handlers(phase2_controller_factory)
    def step_handler(args, **kwargs):
        if str(args.get("run_id", "")).startswith("phase2-"):
            return phase2_handlers["avo_phase2_step"](args, **kwargs)
        return phase1_handlers["avo_step"](args, **kwargs)
    def cancel_handler(args, **kwargs):
        if str(args.get("run_id", "")).startswith("phase2-"):
            return phase2_handlers["avo_phase2_cancel"](args, **kwargs)
        return phase1_handlers["avo_cancel"](args, **kwargs)
    registrations = (
        ("avo_phase0_info", schemas.AVO_PHASE0_INFO,
         lambda args, **kwargs: tools.avo_phase0_info(
             args,
             phase1_enabled=phase1_enabled,
             phase2_enabled=phase2_enabled,
             **kwargs,
         )),
        ("avo_validate_run_spec", schemas.AVO_VALIDATE_RUN_SPEC, tools.avo_validate_run_spec),
        ("avo_create_run", schemas.AVO_CREATE_RUN, phase1_handlers["avo_create_run"]),
        ("avo_step", schemas.AVO_STEP, step_handler),
        ("avo_status", schemas.AVO_STATUS, phase1_handlers["avo_status"]),
        ("avo_cancel", schemas.AVO_CANCEL, cancel_handler),
        ("avo_lineage", schemas.AVO_LINEAGE, phase1_handlers["avo_lineage"]),
        ("avo_create_phase2_run", schemas.AVO_CREATE_PHASE2_RUN,
         phase2_handlers["avo_create_phase2_run"]),
        ("avo_memory", schemas.AVO_MEMORY, phase2_handlers["avo_memory"]),
        ("avo_reconcile", schemas.AVO_RECONCILE, phase2_handlers["avo_reconcile"]),
        ("avo_supervise", schemas.AVO_SUPERVISE, phase2_handlers["avo_supervise"]),
    )
    for name, schema, handler in registrations:
        ctx.register_tool(
            name=name,
            toolset="agentic-variation",
            schema=schema,
            handler=handler,
        )
