from __future__ import annotations

import json
from typing import Any

try:
    from .controller import Phase1DisabledError
    from .phase2 import Phase2DisabledError
    from .phase3 import Phase3DisabledError
    from .phase4 import Phase4DisabledError
    from .phase4_sandbox import SandboxUnavailable, SandboxViolation
    from .contracts import ContractValidationError, RunSpec
    from .state_machine import TransitionError
    from .storage import StorageConflictError, _SCHEMA_VERSION
except ImportError:  # Direct module execution in local tests.
    from controller import Phase1DisabledError
    from phase2 import Phase2DisabledError
    from phase3 import Phase3DisabledError
    from phase4 import Phase4DisabledError
    from phase4_sandbox import SandboxUnavailable, SandboxViolation
    from contracts import ContractValidationError, RunSpec
    from state_machine import TransitionError
    from storage import StorageConflictError, _SCHEMA_VERSION

_TUPLE_FIELDS = ("exclusions", "correctness_predicates", "score_keys", "allowed_toolsets")


def avo_phase0_info(
    args: dict[str, Any], *, phase1_enabled: bool = False, phase2_enabled: bool = False,
    phase3_enabled: bool = False, phase4_enabled: bool = False, **kwargs: Any
) -> str:
    del args, kwargs
    return json.dumps(
        {
            "plugin": "agentic-variation",
            "version": "0.5.0",
            "phase": 4,
            "schema_version": _SCHEMA_VERSION,
            "execution_enabled": phase1_enabled,
            "phase2_execution_enabled": phase2_enabled,
            "phase3_execution_enabled": phase3_enabled,
            "phase4_execution_enabled": phase4_enabled,
            "single_step_only": False,
            "explicit_manual_steps_only": True,
            "max_phase2_steps": 3,
            "max_supervisor_calls": 1,
            "child_toolsets": ["todo"],
            "network_access_enabled": False,
            "phase3_child_toolsets": ["todo"],
            "phase3_controller_mutation": True,
            "phase4_sandbox_required": True,
            "phase4_network_policy": "none",
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


def avo_phase3_step_rejected(args: dict[str, Any], **kwargs: Any) -> str:
    del args, kwargs
    return json.dumps(
        {
            "ok": False,
            "error_type": "Phase3ToolRoutingError",
            "error": "Phase 3 runs must use avo_mutate_phase3, not avo_step.",
        },
        sort_keys=True,
    )


def avo_phase3_tool_rejected(
    args: dict[str, Any], *, tool_name: str, replacement: str, **kwargs: Any
) -> str:
    del args, kwargs
    return json.dumps(
        {
            "ok": False,
            "error_type": "Phase3ToolRoutingError",
            "error": f"Phase 3 runs cannot use {tool_name}; use {replacement}.",
        },
        sort_keys=True,
    )


def make_phase1_handlers(controller_factory):
    def invoke(method_name: str, args: dict[str, Any]) -> str:
        try:
            controller = controller_factory()
            method = getattr(controller, method_name)
            if method_name == "create_run":
                result = method(
                    objective=args.get("objective", ""),
                    approval_receipt=args.get("approval_receipt", ""),
                )
            else:
                result = method(args.get("run_id", ""))
            return json.dumps(result, sort_keys=True)
        except (
            Phase1DisabledError,
            ContractValidationError,
            StorageConflictError,
            TransitionError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            return json.dumps(
                {"ok": False, "error_type": type(exc).__name__, "error": str(exc)[:500]},
                sort_keys=True,
            )

    return {
        "avo_create_run": lambda args, **kwargs: invoke("create_run", args),
        "avo_step": lambda args, **kwargs: invoke("step", args),
        "avo_status": lambda args, **kwargs: invoke("status", args),
        "avo_cancel": lambda args, **kwargs: invoke("cancel", args),
        "avo_lineage": lambda args, **kwargs: invoke("lineage", args),
    }


def make_phase2_handlers(controller_factory):
    def invoke(method_name: str, args: dict[str, Any]) -> str:
        try:
            controller = controller_factory()
            method = getattr(controller, method_name)
            if method_name == "create_run":
                result = method(
                    objective=args.get("objective", ""),
                    approval_receipt=args.get("approval_receipt", ""),
                )
            else:
                result = method(args.get("run_id", ""))
            return json.dumps(result, sort_keys=True)
        except (
            Phase2DisabledError,
            ContractValidationError,
            StorageConflictError,
            TransitionError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            return json.dumps(
                {"ok": False, "error_type": type(exc).__name__, "error": str(exc)[:500]},
                sort_keys=True,
            )

    return {
        "avo_create_phase2_run": lambda args, **kwargs: invoke("create_run", args),
        "avo_phase2_step": lambda args, **kwargs: invoke("step", args),
        "avo_phase2_cancel": lambda args, **kwargs: invoke("cancel", args),
        "avo_memory": lambda args, **kwargs: invoke("memory", args),
        "avo_reconcile": lambda args, **kwargs: invoke("reconcile", args),
        "avo_supervise": lambda args, **kwargs: invoke("supervise", args),
    }


def make_phase3_handlers(controller_factory):
    def invoke(method_name: str, args: dict[str, Any]) -> str:
        try:
            controller = controller_factory()
            method = getattr(controller, method_name)
            if method_name == "create_run":
                result = method(
                    objective=args.get("objective", ""),
                    approval_receipt=args.get("approval_receipt", ""),
                )
            else:
                result = method(args.get("run_id", ""))
            return json.dumps(result, sort_keys=True)
        except (
            Phase3DisabledError,
            ContractValidationError,
            StorageConflictError,
            TransitionError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            return json.dumps(
                {"ok": False, "error_type": type(exc).__name__, "error": str(exc)[:500]},
                sort_keys=True,
            )

    return {
        "avo_create_phase3_run": lambda args, **kwargs: invoke("create_run", args),
        "avo_mutate_phase3": lambda args, **kwargs: invoke("mutate", args),
        "avo_phase3_receipt": lambda args, **kwargs: invoke("receipt", args),
        "avo_phase3_reconcile": lambda args, **kwargs: invoke("reconcile", args),
        "avo_phase3_cancel": lambda args, **kwargs: invoke("cancel", args),
    }


def make_phase4_handlers(controller_factory):
    def invoke(method_name: str, args: dict[str, Any]) -> str:
        try:
            controller = controller_factory()
            method = getattr(controller, method_name)
            if method_name == "create_run":
                result = method(
                    objective=args.get("objective", ""),
                    approval_receipt=args.get("approval_receipt", ""),
                )
            else:
                result = method(args.get("run_id", ""))
            return json.dumps(result, sort_keys=True)
        except (
            Phase4DisabledError,
            SandboxUnavailable,
            SandboxViolation,
            ContractValidationError,
            StorageConflictError,
            TransitionError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            return json.dumps(
                {"ok": False, "error_type": type(exc).__name__, "error": str(exc)[:500]},
                sort_keys=True,
            )

    return {
        "avo_create_phase4_run": lambda args, **kwargs: invoke("create_run", args),
        "avo_patch_phase4": lambda args, **kwargs: invoke("patch", args),
        "avo_phase4_receipt": lambda args, **kwargs: invoke("receipt", args),
        "avo_phase4_reconcile": lambda args, **kwargs: invoke("reconcile", args),
        "avo_phase4_cancel": lambda args, **kwargs: invoke("cancel", args),
    }
