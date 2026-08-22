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

AVO_CREATE_PHASE2_RUN = {
    **AVO_CREATE_RUN,
    "name": "avo_create_phase2_run",
    "description": "Create one approved bounded Phase 2 continuation run.",
}
AVO_MEMORY = _run_id_schema(
    "avo_memory", "Read compact persistent continuation memory for a Phase 2 run."
)
AVO_RECONCILE = _run_id_schema(
    "avo_reconcile", "Reconcile an interrupted Phase 2 run from durable evidence."
)
AVO_SUPERVISE = _run_id_schema(
    "avo_supervise", "Request the one allowed todo-only supervisor advice."
)

AVO_CREATE_PHASE3_RUN = {
    **AVO_CREATE_RUN,
    "name": "avo_create_phase3_run",
    "description": "Create one plugin-owned disposable Phase 3 Git fixture repository.",
}
AVO_MUTATE_PHASE3 = _run_id_schema(
    "avo_mutate_phase3", "Run one todo-only closed-enum mutation and fixed test command."
)
AVO_PHASE3_RECEIPT = _run_id_schema(
    "avo_phase3_receipt", "Read the append-only retained-repository mutation receipt."
)
AVO_PHASE3_RECONCILE = _run_id_schema(
    "avo_phase3_reconcile", "Reconcile interrupted Phase 3 state without rerunning effects."
)

AVO_CREATE_PHASE4_RUN = {
    **AVO_CREATE_RUN,
    "name": "avo_create_phase4_run",
    "description": "Create one pinned, networkless Phase 4 patch-sandbox run.",
}
AVO_PATCH_PHASE4 = _run_id_schema(
    "avo_patch_phase4", "Run one bounded model-authored patch in the pinned Docker sandbox."
)
AVO_PHASE4_RECEIPT = _run_id_schema(
    "avo_phase4_receipt", "Read the append-only Phase 4 sandbox receipt."
)
AVO_PHASE4_RECONCILE = _run_id_schema(
    "avo_phase4_reconcile", "Reconcile Phase 4 state without rerunning sandbox effects."
)
