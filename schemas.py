AVO_PHASE0_INFO = {
    "name": "avo_phase0_info",
    "description": (
        "Report the installed Agentic Variation plugin phase and safety posture. "
        "Phase 0 performs no model calls, child launches, commands, or experiment execution."
    ),
    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
}

AVO_VALIDATE_RUN_SPEC = {
    "name": "avo_validate_run_spec",
    "description": (
        "Validate and hash an Agentic Variation RunSpec without persisting or executing it. "
        "Use this only to check Phase 0 contract shape and deterministic identity."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "run_spec": {
                "type": "object",
                "description": "Complete avo.run-spec.v1 payload to validate.",
            }
        },
        "required": ["run_spec"],
        "additionalProperties": False,
    },
}

AVO_CREATE_RUN = {
    "name": "avo_create_run",
    "description": "Create one approved plugin-owned Phase 1 fixture run.",
    "parameters": {
        "type": "object",
        "properties": {
            "objective": {"type": "string", "description": "Bounded fixture objective."},
            "approval_receipt": {"type": "string", "description": "Explicit user approval reference."},
        },
        "required": ["objective", "approval_receipt"],
        "additionalProperties": False,
    },
}


def _run_id_schema(name, description):
    return {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": {"run_id": {"type": "string"}},
            "required": ["run_id"],
            "additionalProperties": False,
        },
    }


AVO_STEP = _run_id_schema(
    "avo_step", "Run exactly one no-file/no-command Phase 1 child step on the built-in fixture."
)
AVO_STATUS = _run_id_schema("avo_status", "Read the current state of a Phase 1 fixture run.")
AVO_CANCEL = _run_id_schema("avo_cancel", "Cancel a Phase 1 run before its child step begins.")
AVO_LINEAGE = _run_id_schema(
    "avo_lineage", "Read candidate and evaluation evidence for a Phase 1 fixture run."
)
