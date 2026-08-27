from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DESKTOP_PLUGIN = ROOT / "desktop" / "plugin.js"
LEGACY_VARIATION_LABEL = "Phase" + " 5"


def test_desktop_companion_is_opt_in_and_registers_a_configuration_page():
    source = DESKTOP_PLUGIN.read_text(encoding="utf-8")

    assert "const ID = 'agentic-variation'" in source
    assert "defaultEnabled: false" in source
    assert "ROUTES_AREA" in source
    assert "SIDEBAR_NAV_AREA" in source
    assert "PALETTE_AREA" in source
    assert "const ROUTE = '/agentic-variation'" in source
    assert "data: { path: ROUTE }" in source
    assert "label: 'Agentic Variation'" in source


def test_desktop_configuration_options_are_persisted_in_plugin_storage():
    source = DESKTOP_PLUGIN.read_text(encoding="utf-8")
    keys = {
        "defaultMaxSteps",
        "defaultMaxWallSeconds",
        "defaultMaxCostUsd",
        "defaultNoProgressLimit",
        "networkPolicy",
        "allowedToolsets",
        "evaluatorId",
    }

    for key in keys:
        assert f"'{key}'" in source
    assert "storage.get" in source
    assert "storage.set" in source
    assert "backend-owned in config.yaml" in source


def test_desktop_plugin_uses_only_supported_imports_and_theme_safe_styles():
    source = DESKTOP_PLUGIN.read_text(encoding="utf-8")
    imports = set(re.findall(r"from\s+['\"]([^'\"]+)['\"]", source))

    assert imports <= {"@hermes/plugin-sdk", "react", "react/jsx-runtime"}
    assert re.search(r"#[0-9a-fA-F]{3,8}\b|\brgb\(|\bblack\b|\bwhite\b", source) is None


def test_native_manifest_declares_matching_configurable_defaults():
    manifest = (ROOT / "plugin.yaml").read_text(encoding="utf-8")
    source = DESKTOP_PLUGIN.read_text(encoding="utf-8")

    assert "config_schema:" in manifest
    assert re.search(r"^  phase1_enabled:\s*", manifest, re.MULTILINE)
    assert re.search(r"^  phase1_wait_seconds:\s*", manifest, re.MULTILINE)
    assert re.search(r"^  phase2_enabled:\s*", manifest, re.MULTILINE)
    assert re.search(r"^  phase2_wait_seconds:\s*", manifest, re.MULTILINE)
    assert re.search(r"^  phase3_enabled:\s*", manifest, re.MULTILINE)
    assert re.search(r"^  phase3_wait_seconds:\s*", manifest, re.MULTILINE)
    assert re.search(r"^  phase3_test_timeout_seconds:\s*", manifest, re.MULTILINE)
    assert re.search(r"^  phase4_enabled:\s*", manifest, re.MULTILINE)
    assert re.search(r"^  phase4_wait_seconds:\s*", manifest, re.MULTILINE)
    assert re.search(r"^  phase4_sandbox_timeout_seconds:\s*", manifest, re.MULTILINE)
    assert re.search(r"^  phase4_enabled:\s*", manifest, re.MULTILINE)
    assert re.search(r"^  phase4_wait_seconds:\s*", manifest, re.MULTILINE)
    assert re.search(r"^  phase4_sandbox_timeout_seconds:\s*", manifest, re.MULTILINE)
    assert "cannot be enabled from Desktop" in source
    for key in (
        "default_max_steps",
        "default_max_wall_seconds",
        "default_max_cost_usd",
        "default_no_progress_limit",
        "network_policy",
        "allowed_toolsets",
        "evaluator_id",
    ):
        assert re.search(rf"^  {key}:\s*", manifest, re.MULTILINE)


def test_desktop_plugin_is_valid_javascript_when_node_is_available():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is unavailable")

    result = subprocess.run(
        [node, "--check", str(DESKTOP_PLUGIN)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_variation_cycle_defaults_are_closed_and_desktop_is_explanatory_only():
    manifest=(ROOT/"plugin.yaml").read_text(encoding="utf-8")
    source=DESKTOP_PLUGIN.read_text(encoding="utf-8")
    assert "version: 0.6.0" in manifest
    assert re.search(r"^  phase5_enabled:\s*\n\s*type: bool\n\s*default: false",manifest,re.MULTILINE)
    assert re.search(r"^  phase5_wait_seconds:",manifest,re.MULTILINE)
    assert re.search(r"^  phase5_sandbox_timeout_seconds:",manifest,re.MULTILINE)
    assert "Variation Cycle" in source
    assert "cannot enable Variation Cycles" in source
    assert LEGACY_VARIATION_LABEL not in source
    assert "phase5_enabled" not in source
