from __future__ import annotations

import json
from typing import Any

try:
    from .contracts import ContractValidationError, RunSpec
    from .storage import _SCHEMA_VERSION
except ImportError:  # Direct module execution in local tests.
    from contracts import ContractValidationError, RunSpec
    from storage import _SCHEMA_VERSION

_TUPLE_FIELDS = ("exclusions", "correctness_predicates", "score_keys", "allowed_toolsets")


def avo_phase0_info(args: dict[str, Any], **kwargs: Any) -> str:
    del args, kwargs
    return json.dumps(
        {
            "plugin": "agentic-variation",
            "version": "0.1.0",
            "phase": 0,
            "schema_version": _SCHEMA_VERSION,
            "execution_enabled": False,
            "model_calls_enabled": False,
            "subagent_launches_enabled": False,
            "network_access_enabled": False,
        },
        sort_keys=True,
    )


def avo_validate_run_spec(args: dict[str, Any], **kwargs: Any) -> str:
    del kwargs
    try:
        payload = args.get("run_spec")
        if not isinstance(payload, dict):
            raise ContractValidationError("run_spec must be an object")
        values = dict(payload)
        for name in _TUPLE_FIELDS:
            if name in values and isinstance(values[name], list):
                values[name] = tuple(values[name])
        spec = RunSpec(**values)
        result = {
            "valid": True,
            "contract_version": spec.contract_version,
            "run_spec_hash": spec.identity,
        }
    except (ContractValidationError, TypeError, ValueError) as exc:
        result = {
            "valid": False,
            "error_type": type(exc).__name__,
            "error": str(exc)[:300],
        }
    return json.dumps(result, sort_keys=True)
