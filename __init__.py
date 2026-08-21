"""Hermes Agentic Variation plugin registration."""

try:
    from . import schemas, tools
except ImportError:  # Pytest can collect a repository-root plugin as top-level __init__.
    import schemas
    import tools


def register(ctx):
    """Register read-only inspection plus the backend-gated single-step Phase 1 tools."""
    phase1_enabled = ctx.get_config("phase1_enabled", default=False) is True
    raw_wait = ctx.get_config("phase1_wait_seconds", default=120)
    wait_seconds = raw_wait if type(raw_wait) is int and 5 <= raw_wait <= 180 else 120
    controller_instance = None

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

    phase1_handlers = tools.make_phase1_handlers(controller_factory)
    registrations = (
        ("avo_phase0_info", schemas.AVO_PHASE0_INFO,
         lambda args, **kwargs: tools.avo_phase0_info(
             args, phase1_enabled=phase1_enabled, **kwargs
         )),
        ("avo_validate_run_spec", schemas.AVO_VALIDATE_RUN_SPEC, tools.avo_validate_run_spec),
        ("avo_create_run", schemas.AVO_CREATE_RUN, phase1_handlers["avo_create_run"]),
        ("avo_step", schemas.AVO_STEP, phase1_handlers["avo_step"]),
        ("avo_status", schemas.AVO_STATUS, phase1_handlers["avo_status"]),
        ("avo_cancel", schemas.AVO_CANCEL, phase1_handlers["avo_cancel"]),
        ("avo_lineage", schemas.AVO_LINEAGE, phase1_handlers["avo_lineage"]),
    )
    for name, schema, handler in registrations:
        ctx.register_tool(
            name=name,
            toolset="agentic-variation",
            schema=schema,
            handler=handler,
        )
