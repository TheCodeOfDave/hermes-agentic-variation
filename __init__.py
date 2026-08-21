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
    phase3_enabled = ctx.get_config("phase3_enabled", default=False) is True
    raw_wait = ctx.get_config("phase1_wait_seconds", default=120)
    wait_seconds = raw_wait if type(raw_wait) is int and 5 <= raw_wait <= 180 else 120
    raw_phase2_wait = ctx.get_config("phase2_wait_seconds", default=120)
    phase2_wait_seconds = (
        raw_phase2_wait
        if type(raw_phase2_wait) is int and 5 <= raw_phase2_wait <= 180
        else 120
    )
    raw_phase3_wait = ctx.get_config("phase3_wait_seconds", default=120)
    phase3_wait_seconds = (
        raw_phase3_wait
        if type(raw_phase3_wait) is int and 5 <= raw_phase3_wait <= 180
        else 120
    )
    raw_test_timeout = ctx.get_config("phase3_test_timeout_seconds", default=20)
    phase3_test_timeout_seconds = (
        raw_test_timeout if type(raw_test_timeout) is int and 1 <= raw_test_timeout <= 60 else 20
    )
    controller_instance = None
    phase2_controller_instance = None
    phase3_controller_instance = None

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

    def phase3_controller_factory():
        nonlocal phase3_controller_instance
        if phase3_controller_instance is None:
            from plugins.plugin_storage import plugin_data_dir

            try:
                from .phase3 import Phase3Controller
                from .phase3_workspace import Phase3Workspace
                from .runtime import HermesLifecycleAdapter
                from .storage import RunStore
            except ImportError:
                from phase3 import Phase3Controller
                from phase3_workspace import Phase3Workspace
                from runtime import HermesLifecycleAdapter
                from storage import RunStore

            data_dir = plugin_data_dir("agentic-variation")
            phase3_controller_instance = Phase3Controller(
                store=RunStore(data_dir / "phase1.db"),
                lifecycle=HermesLifecycleAdapter(ctx.subagent_lifecycle, phase=3),
                workspace=Phase3Workspace(
                    data_dir / "phase3-runs",
                    test_timeout_seconds=phase3_test_timeout_seconds,
                ),
                enabled=phase3_enabled,
                wait_seconds=phase3_wait_seconds,
            )
        return phase3_controller_instance

    phase1_handlers = tools.make_phase1_handlers(controller_factory)
    phase2_handlers = tools.make_phase2_handlers(phase2_controller_factory)
    phase3_handlers = tools.make_phase3_handlers(phase3_controller_factory)
    def step_handler(args, **kwargs):
        if str(args.get("run_id", "")).startswith("phase3-"):
            return tools.avo_phase3_step_rejected(args, **kwargs)
        if str(args.get("run_id", "")).startswith("phase2-"):
            return phase2_handlers["avo_phase2_step"](args, **kwargs)
        return phase1_handlers["avo_step"](args, **kwargs)
    def cancel_handler(args, **kwargs):
        if str(args.get("run_id", "")).startswith("phase3-"):
            return phase3_handlers["avo_phase3_cancel"](args, **kwargs)
        if str(args.get("run_id", "")).startswith("phase2-"):
            return phase2_handlers["avo_phase2_cancel"](args, **kwargs)
        return phase1_handlers["avo_cancel"](args, **kwargs)
    def phase2_only_handler(tool_name, replacement, phase2_handler):
        def handler(args, **kwargs):
            if str(args.get("run_id", "")).startswith("phase3-"):
                return tools.avo_phase3_tool_rejected(
                    args,
                    tool_name=tool_name,
                    replacement=replacement,
                    **kwargs,
                )
            return phase2_handler(args, **kwargs)
        return handler
    registrations = (
        ("avo_phase0_info", schemas.AVO_PHASE0_INFO,
         lambda args, **kwargs: tools.avo_phase0_info(
             args,
             phase1_enabled=phase1_enabled,
             phase2_enabled=phase2_enabled,
             phase3_enabled=phase3_enabled,
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
        ("avo_memory", schemas.AVO_MEMORY,
         phase2_only_handler(
             "avo_memory", "avo_phase3_receipt", phase2_handlers["avo_memory"]
         )),
        ("avo_reconcile", schemas.AVO_RECONCILE,
         phase2_only_handler(
             "avo_reconcile", "avo_phase3_reconcile", phase2_handlers["avo_reconcile"]
         )),
        ("avo_supervise", schemas.AVO_SUPERVISE,
         phase2_only_handler(
             "avo_supervise", "avo_mutate_phase3", phase2_handlers["avo_supervise"]
         )),
        ("avo_create_phase3_run", schemas.AVO_CREATE_PHASE3_RUN,
         phase3_handlers["avo_create_phase3_run"]),
        ("avo_mutate_phase3", schemas.AVO_MUTATE_PHASE3,
         phase3_handlers["avo_mutate_phase3"]),
        ("avo_phase3_receipt", schemas.AVO_PHASE3_RECEIPT,
         phase3_handlers["avo_phase3_receipt"]),
        ("avo_phase3_reconcile", schemas.AVO_PHASE3_RECONCILE,
         phase3_handlers["avo_phase3_reconcile"]),
    )
    for name, schema, handler in registrations:
        ctx.register_tool(
            name=name,
            toolset="agentic-variation",
            schema=schema,
            handler=handler,
        )
