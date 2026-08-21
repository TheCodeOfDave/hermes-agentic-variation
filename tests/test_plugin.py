from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from contracts import RunSpec

HEX_A = "a" * 64
ROOT = Path(__file__).resolve().parents[1]


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
    }
    assert {tool["toolset"] for tool in ctx.tools.values()} == {"agentic-variation"}
    assert all(tool["schema"]["name"] == name for name, tool in ctx.tools.items())


def test_info_handler_reports_phase1_backend_gate_is_off_by_default():
    plugin = load_plugin_module()
    ctx = FakeContext()
    plugin.register(ctx)

    result = json.loads(ctx.tools["avo_phase0_info"]["handler"]({}))

    assert result["phase"] == 2
    assert result["execution_enabled"] is False
    assert result["phase2_execution_enabled"] is False
    assert result["single_step_only"] is False
    assert result["explicit_manual_steps_only"] is True
    assert result["max_phase2_steps"] == 3
    assert result["max_supervisor_calls"] == 1
    assert result["schema_version"] == 3


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
