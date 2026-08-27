from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

from contracts import RunSpec

HEX_A = "a" * 64
ROOT = Path(__file__).resolve().parents[1]
LEGACY_VARIATION_LABEL = "Phase" + " 5"
DOCUMENTATION = (ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md")))
FORBIDDEN_ENVIRONMENT_MARKERS = (
    "Seren" + "ity",
    "hermes" + "-owner",
    "dc" + "-workstation",
    "Windows " + "11",
    "Windows " + "10",
    "/opt/data/" + "plugin-data/",
)
FORBIDDEN_ENVIRONMENT_PATTERNS = (
    re.compile(r"\bphase[1-5]-[0-9a-f]{8,}\b", re.IGNORECASE),
    re.compile(r"\b\d+% used\b", re.IGNORECASE),
    re.compile(r"\b\d+ GB free\b", re.IGNORECASE),
    re.compile(r"upstream\s+`[0-9a-f]{8}`", re.IGNORECASE),
    re.compile(r"\b20\d{6}_[0-9]{6}_[0-9a-f]{6}\b", re.IGNORECASE),
)
FORBIDDEN_OPERATIONAL_DETAILS = (
    "API and containers healthy with zero restarts",
    "Acceptance tooling left `.venv`, `.pytest_cache`, and `.ruff_cache`",
)


def load_plugin_module():
    spec = importlib.util.spec_from_file_location(
        "agentic_variation_plugin",
        ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)],
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeContext:
    def __init__(self):
        self.tools = {}
        self.subagent_lifecycle = object()

    def register_tool(self, *, name, toolset, schema, handler):
        self.tools[name] = {"toolset": toolset, "schema": schema, "handler": handler}

    def get_config(self, key, default=None):
        return default


def valid_payload() -> dict:
    return {
        "run_id": "run-plugin",
        "target_root": "/workspace/example",
        "seed_digest": HEX_A,
        "objective": "Validate a RunSpec without executing it.",
        "exclusions": ["No execution"],
        "evaluator_id": "fixture.score.v1",
        "evaluator_config": {},
        "correctness_predicates": ["tests_pass"],
        "score_keys": ["score"],
        "comparison": "maximize",
        "allowed_toolsets": ["file"],
        "network_policy": "disabled",
        "max_steps": 3,
        "max_wall_seconds": 60,
        "max_cost_usd": 1.0,
        "no_progress_limit": 2,
        "approval_receipt": "approved",
    }


def test_plugin_registers_phase0_compatibility_and_bounded_phase1_tools():
    plugin = load_plugin_module()
    ctx = FakeContext()

    plugin.register(ctx)

    assert set(ctx.tools) == {
        "avo_phase0_info",
        "avo_validate_run_spec",
        "avo_create_run",
        "avo_step",
        "avo_status",
        "avo_cancel",
        "avo_lineage",
        "avo_create_phase2_run",
        "avo_memory",
        "avo_reconcile",
        "avo_supervise",
        "avo_create_phase3_run",
        "avo_mutate_phase3",
        "avo_phase3_receipt",
        "avo_phase3_reconcile",
        "avo_create_phase4_run",
        "avo_patch_phase4",
        "avo_phase4_receipt",
        "avo_phase4_reconcile",
        "avo_create_phase5_run",
        "avo_patchset_phase5",
        "avo_phase5_receipt",
        "avo_phase5_reconcile",
    }
    assert {tool["toolset"] for tool in ctx.tools.values()} == {"agentic-variation"}
    assert all(tool["schema"]["name"] == name for name, tool in ctx.tools.items())


def test_info_handler_reports_phase1_backend_gate_is_off_by_default():
    plugin = load_plugin_module()
    ctx = FakeContext()
    plugin.register(ctx)

    result = json.loads(ctx.tools["avo_phase0_info"]["handler"]({}))

    assert result["phase"] == 5
    assert result["execution_enabled"] is False
    assert result["phase2_execution_enabled"] is False
    assert result["phase3_execution_enabled"] is False
    assert result["phase4_execution_enabled"] is False
    assert result["single_step_only"] is False
    assert result["explicit_manual_steps_only"] is True
    assert result["max_phase2_steps"] == 3
    assert result["max_supervisor_calls"] == 1
    assert result["schema_version"] == 6
    assert result["phase3_child_toolsets"] == ["todo"]
    assert result["phase3_controller_mutation"] is True
    assert result["phase4_sandbox_required"] is True
    assert result["phase4_network_policy"] == "none"


def test_generic_step_rejects_phase3_run_without_launching_phase1_controller():
    plugin = load_plugin_module()
    ctx = FakeContext()
    plugin.register(ctx)

    result = json.loads(ctx.tools["avo_step"]["handler"]({"run_id": "phase3-abcdef"}))

    assert result["ok"] is False
    assert result["error_type"] == "Phase3ToolRoutingError"
    assert "avo_mutate_phase3" in result["error"]


def test_phase2_only_tools_reject_phase3_run_ids():
    plugin = load_plugin_module()
    ctx = FakeContext()
    plugin.register(ctx)

    expected = {
        "avo_memory": "avo_phase3_receipt",
        "avo_reconcile": "avo_phase3_reconcile",
        "avo_supervise": "avo_mutate_phase3",
    }
    for tool_name, replacement in expected.items():
        result = json.loads(ctx.tools[tool_name]["handler"]({"run_id": "phase3-abcdef"}))
        assert result["ok"] is False
        assert result["error_type"] == "Phase3ToolRoutingError"
        assert replacement in result["error"]


def test_generic_and_phase2_tools_reject_phase4_run_ids():
    plugin = load_plugin_module()
    ctx = FakeContext()
    plugin.register(ctx)
    expected = {
        "avo_step": "avo_patch_phase4",
        "avo_memory": "avo_phase4_receipt",
        "avo_reconcile": "avo_phase4_reconcile",
        "avo_supervise": "avo_patch_phase4",
    }

    for tool_name, replacement in expected.items():
        result = json.loads(ctx.tools[tool_name]["handler"]({"run_id": "phase4-abcdef"}))
        assert result["ok"] is False
        assert replacement in result["error"]


def test_validate_handler_returns_stable_identity_for_valid_payload():
    plugin = load_plugin_module()
    ctx = FakeContext()
    plugin.register(ctx)

    handler = ctx.tools["avo_validate_run_spec"]["handler"]
    first = json.loads(handler({"run_spec": valid_payload()}))
    second = json.loads(handler({"run_spec": valid_payload()}))

    assert first == second
    assert first == {
        "valid": True,
        "contract_version": RunSpec.contract_version,
        "run_spec_hash": first["run_spec_hash"],
    }
    assert len(first["run_spec_hash"]) == 64


def test_validate_handler_returns_bounded_error_instead_of_raising():
    plugin = load_plugin_module()
    ctx = FakeContext()
    plugin.register(ctx)

    result = json.loads(
        ctx.tools["avo_validate_run_spec"]["handler"](
            {"run_spec": {**valid_payload(), "network_policy": "internet"}}
        )
    )

    assert result["valid"] is False
    assert result["error_type"] == "ContractValidationError"
    assert "network_policy" in result["error"]
    assert len(result["error"]) <= 300


def test_phase5_plugin_registers_23_tools_disabled_defaults_and_cross_phase_routing():
    plugin = load_plugin_module()
    ctx = FakeContext()
    plugin.register(ctx)
    assert len(ctx.tools)==23
    expected={"avo_create_phase5_run","avo_patchset_phase5","avo_phase5_receipt","avo_phase5_reconcile"}
    assert expected <= set(ctx.tools)
    info=json.loads(ctx.tools["avo_phase0_info"]["handler"]({}))
    assert info["phase"]==5 and info["version"]=="0.6.0"
    assert info["phase5_execution_enabled"] is False and info["schema_version"]==6
    for name in set(ctx.tools)-expected-{"avo_phase0_info","avo_validate_run_spec"}:
        result=json.loads(ctx.tools[name]["handler"]({"run_id":"phase5-abcdef"}))
        assert result["ok"] is False and result["error_type"]=="VariationCycleToolRoutingError"


def test_phase5_does_not_break_legacy_factory_run_namespaces():
    import tools as phase_tools

    class Stub:
        def __getattr__(self, name):
            return lambda run_id: {"method": name, "run_id": run_id}

    cases = [
        (phase_tools.make_phase1_handlers, "avo_status", "phase1-own-run"),
        (phase_tools.make_phase2_handlers, "avo_memory", "phase2-own-run"),
        (phase_tools.make_phase3_handlers, "avo_phase3_receipt", "phase3-own-run"),
        (phase_tools.make_phase4_handlers, "avo_phase4_receipt", "phase4-own-run"),
    ]
    for factory, tool_name, run_id in cases:
        result = json.loads(factory(lambda: Stub())[tool_name]({"run_id": run_id}))
        assert result == {"method": result["method"], "run_id": run_id}
        assert "error_type" not in result


def test_phase5_package_import_ignores_foreign_bare_modules(tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    code = f"""
import importlib.util, pathlib, sys, types
root = pathlib.Path({str(root)!r})
sys.modules['tools'] = types.ModuleType('tools')
sys.modules['contracts'] = types.ModuleType('contracts')
parent = types.ModuleType('hermes_plugins')
parent.__path__ = []
sys.modules['hermes_plugins'] = parent
name = 'hermes_plugins.agentic_variation_import_test'
spec = importlib.util.spec_from_file_location(name, root / '__init__.py', submodule_search_locations=[str(root)])
module = importlib.util.module_from_spec(spec)
module.__package__ = name
module.__path__ = [str(root)]
sys.modules[name] = module
spec.loader.exec_module(module)
assert pathlib.Path(module.tools.__file__).resolve() == (root / 'tools.py').resolve()
assert hasattr(module.tools, 'make_phase1_handlers')
"""
    result = subprocess.run([sys.executable, '-c', code], cwd=tmp_path, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_phase5_handler_bounds_docker_unavailable_factory_error():
    import tools as phase_tools
    from phase5_sandbox import Phase5SandboxUnavailable

    def unavailable():
        raise Phase5SandboxUnavailable("Docker unavailable")

    handler = phase_tools.make_phase5_handlers(unavailable)["avo_create_phase5_run"]
    result = json.loads(handler({"objective": "patch", "approval_receipt": "approved"}))
    assert result == {
        "ok": False,
        "error_type": "VariationCycleUnavailable",
        "error": "Docker unavailable",
    }


def test_variation_cycle_operator_surfaces_do_not_expose_phase_label():
    operator_surfaces = (
        ROOT / "README.md",
        ROOT / "plugin.yaml",
        ROOT / "schemas.py",
        ROOT / "contracts.py",
        ROOT / "phase5.py",
        ROOT / "phase5_fixture.py",
        ROOT / "phase5_patch.py",
        ROOT / "phase5_sandbox.py",
        ROOT / "storage.py",
        ROOT / "tools.py",
        ROOT / "desktop" / "plugin.js",
    )
    for path in operator_surfaces:
        assert LEGACY_VARIATION_LABEL not in path.read_text(encoding="utf-8"), path.relative_to(ROOT)

    public_documents = (ROOT / "README.md", *(ROOT / "docs").glob("*.md"))
    for path in public_documents:
        assert LEGACY_VARIATION_LABEL not in path.read_text(encoding="utf-8"), path.relative_to(ROOT)
        assert "PHASE5" not in path.name, path.relative_to(ROOT)

    plugin = load_plugin_module()
    ctx = FakeContext()
    plugin.register(ctx)
    disabled = json.loads(
        ctx.tools["avo_create_phase5_run"]["handler"](
            {"objective": "vary artifact", "approval_receipt": "approved"}
        )
    )
    assert disabled["error_type"] == "VariationCycleDisabledError"
    assert "Variation Cycle" in disabled["error"]
    assert LEGACY_VARIATION_LABEL not in json.dumps(disabled)


def test_public_documentation_is_system_neutral():
    findings = []
    for path in DOCUMENTATION:
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(ROOT)
        for marker in FORBIDDEN_ENVIRONMENT_MARKERS:
            if marker.casefold() in text.casefold():
                findings.append(f"{relative}: environment marker")
        for pattern in FORBIDDEN_ENVIRONMENT_PATTERNS:
            if pattern.search(text):
                findings.append(f"{relative}: {pattern.pattern}")
        for detail in FORBIDDEN_OPERATIONAL_DETAILS:
            if detail.casefold() in text.casefold():
                findings.append(f"{relative}: operational fingerprint")

    assert not findings, "system-specific public documentation:\n" + "\n".join(findings)