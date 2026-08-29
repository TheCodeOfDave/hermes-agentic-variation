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
    phase4_enabled = ctx.get_config("phase4_enabled", default=False) is True
    phase5_enabled = ctx.get_config("phase5_enabled", default=False) is True
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
    raw_phase4_wait = ctx.get_config("phase4_wait_seconds", default=120)
    phase4_wait_seconds = (
        raw_phase4_wait
        if type(raw_phase4_wait) is int and 5 <= raw_phase4_wait <= 180
        else 120
    )
    raw_sandbox_timeout = ctx.get_config("phase4_sandbox_timeout_seconds", default=30)
    phase4_sandbox_timeout_seconds = (
        raw_sandbox_timeout
        if type(raw_sandbox_timeout) is int and 5 <= raw_sandbox_timeout <= 120
        else 30
    )
    raw_phase5_wait = ctx.get_config("phase5_wait_seconds", default=120)
    phase5_wait_seconds = raw_phase5_wait if type(raw_phase5_wait) is int and 5 <= raw_phase5_wait <= 180 else 120
    raw_phase5_timeout = ctx.get_config("phase5_sandbox_timeout_seconds", default=30)
    phase5_sandbox_timeout_seconds = raw_phase5_timeout if type(raw_phase5_timeout) is int and 5 <= raw_phase5_timeout <= 120 else 30
    controller_instance = None
    phase2_controller_instance = None
    phase3_controller_instance = None
    phase4_controller_instance = None
    phase5_controller_instance = None

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

    def phase4_controller_factory():
        nonlocal phase4_controller_instance
        if phase4_controller_instance is None:
            from plugins.plugin_storage import plugin_data_dir

            try:
                from .phase3_workspace import Phase3Workspace
                from .phase4 import Phase4Controller
                from .phase4_sandbox import DockerSandbox
                from .runtime import HermesLifecycleAdapter
                from .storage import RunStore
            except ImportError:
                from phase3_workspace import Phase3Workspace
                from phase4 import Phase4Controller
                from phase4_sandbox import DockerSandbox
                from runtime import HermesLifecycleAdapter
                from storage import RunStore

            data_dir = plugin_data_dir("agentic-variation")
            phase4_controller_instance = Phase4Controller(
                store=RunStore(data_dir / "phase1.db"),
                lifecycle=HermesLifecycleAdapter(ctx.subagent_lifecycle, phase=4),
                workspace=Phase3Workspace(
                    data_dir / "phase4-runs",
                    test_timeout_seconds=20,
                    repository_prefix="phase4",
                ),
                sandbox=DockerSandbox(
                    data_dir / "phase4-sandbox",
                    timeout_seconds=phase4_sandbox_timeout_seconds,
                ),
                artifact_root=data_dir / "phase4-artifacts",
                enabled=phase4_enabled,
                wait_seconds=phase4_wait_seconds,
            )
        return phase4_controller_instance

    def phase5_controller_factory():
        nonlocal phase5_controller_instance
        if phase5_controller_instance is None:
            from plugins.plugin_storage import plugin_data_dir
            try:
                from .phase5 import Phase5Controller
                from .phase5_fixture import Phase5Fixture
                from .phase5_sandbox import Phase5DockerSandbox
                from .runtime import HermesLifecycleAdapter
                from .storage import RunStore
            except ImportError:
                from phase5 import Phase5Controller
                from phase5_fixture import Phase5Fixture
                from phase5_sandbox import Phase5DockerSandbox
                from runtime import HermesLifecycleAdapter
                from storage import RunStore
            data_dir = plugin_data_dir("agentic-variation")
            phase5_controller_instance = Phase5Controller(
                store=RunStore(data_dir / "phase1.db"),
                lifecycle=HermesLifecycleAdapter(ctx.subagent_lifecycle, phase=5),
                fixture=Phase5Fixture(data_dir / "phase5-runs"),
                sandbox=Phase5DockerSandbox(data_dir / "phase5-sandbox", timeout_seconds=phase5_sandbox_timeout_seconds),
                artifact_root=data_dir / "phase5-artifacts",
                enabled=phase5_enabled,
                wait_seconds=phase5_wait_seconds,
            )
        return phase5_controller_instance
    phase1_handlers = tools.make_phase1_handlers(controller_factory)
    phase2_handlers = tools.make_phase2_handlers(phase2_controller_factory)
    phase3_handlers = tools.make_phase3_handlers(phase3_controller_factory)
    phase4_handlers = tools.make_phase4_handlers(phase4_controller_factory)
    phase5_handlers = tools.make_phase5_handlers(phase5_controller_factory, enabled=phase5_enabled)
    def step_handler(args, **kwargs):
        if str(args.get("run_id", "")).startswith("phase4-"):
            return tools.avo_phase3_tool_rejected(
                args, tool_name="avo_step", replacement="avo_patch_phase4", **kwargs
            )
        if str(args.get("run_id", "")).startswith("phase3-"):
            return tools.avo_phase3_step_rejected(args, **kwargs)
        if str(args.get("run_id", "")).startswith("phase2-"):
            return phase2_handlers["avo_phase2_step"](args, **kwargs)
        return phase1_handlers["avo_step"](args, **kwargs)
    def cancel_handler(args, **kwargs):
        if str(args.get("run_id", "")).startswith("phase4-"):
            return phase4_handlers["avo_phase4_cancel"](args, **kwargs)
        if str(args.get("run_id", "")).startswith("phase3-"):
            return phase3_handlers["avo_phase3_cancel"](args, **kwargs)
        if str(args.get("run_id", "")).startswith("phase2-"):
            return phase2_handlers["avo_phase2_cancel"](args, **kwargs)
        return phase1_handlers["avo_cancel"](args, **kwargs)
    def phase2_only_handler(tool_name, replacement, phase4_replacement, phase2_handler):
        def handler(args, **kwargs):
            if str(args.get("run_id", "")).startswith("phase4-"):
                return tools.avo_phase3_tool_rejected(
                    args,
                    tool_name=tool_name,
                    replacement=phase4_replacement,
                    **kwargs,
                )
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
             phase4_enabled=phase4_enabled,
             phase5_enabled=phase5_enabled,
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
             "avo_memory", "avo_phase3_receipt", "avo_phase4_receipt",
             phase2_handlers["avo_memory"]
         )),
        ("avo_reconcile", schemas.AVO_RECONCILE,
         phase2_only_handler(
             "avo_reconcile", "avo_phase3_reconcile", "avo_phase4_reconcile",
             phase2_handlers["avo_reconcile"]
         )),
        ("avo_supervise", schemas.AVO_SUPERVISE,
         phase2_only_handler(
             "avo_supervise", "avo_mutate_phase3", "avo_patch_phase4",
             phase2_handlers["avo_supervise"]
         )),
        ("avo_create_phase3_run", schemas.AVO_CREATE_PHASE3_RUN,
         phase3_handlers["avo_create_phase3_run"]),
        ("avo_mutate_phase3", schemas.AVO_MUTATE_PHASE3,
         phase3_handlers["avo_mutate_phase3"]),
        ("avo_phase3_receipt", schemas.AVO_PHASE3_RECEIPT,
         phase3_handlers["avo_phase3_receipt"]),
        ("avo_phase3_reconcile", schemas.AVO_PHASE3_RECONCILE,
         phase3_handlers["avo_phase3_reconcile"]),
        ("avo_create_phase4_run", schemas.AVO_CREATE_PHASE4_RUN,
         phase4_handlers["avo_create_phase4_run"]),
        ("avo_patch_phase4", schemas.AVO_PATCH_PHASE4,
         phase4_handlers["avo_patch_phase4"]),
        ("avo_phase4_receipt", schemas.AVO_PHASE4_RECEIPT,
         phase4_handlers["avo_phase4_receipt"]),
        ("avo_phase4_reconcile", schemas.AVO_PHASE4_RECONCILE,
         phase4_handlers["avo_phase4_reconcile"]),        ("avo_create_phase5_run", schemas.AVO_CREATE_PHASE5_RUN,
         phase5_handlers["avo_create_phase5_run"]),
        ("avo_patchset_phase5", schemas.AVO_PATCHSET_PHASE5,
         phase5_handlers["avo_patchset_phase5"]),
        ("avo_phase5_receipt", schemas.AVO_PHASE5_RECEIPT,
         phase5_handlers["avo_phase5_receipt"]),
        ("avo_phase5_reconcile", schemas.AVO_PHASE5_RECONCILE,
         phase5_handlers["avo_phase5_reconcile"]),
    )
    phase5_tool_names = {"avo_create_phase5_run", "avo_patchset_phase5", "avo_phase5_receipt", "avo_phase5_reconcile"}
    for name, schema, handler in registrations:
        if name not in phase5_tool_names:
            original = handler
            def handler(args, _original=original, _name=name, **kwargs):
                if str(args.get("run_id", "")).startswith("phase5-"):
                    return tools.avo_phase5_tool_rejected(args, tool_name=_name, **kwargs)
                return _original(args, **kwargs)
        ctx.register_tool(
            name=name,
            toolset="agentic-variation",
            schema=schema,
            handler=handler,
        )
