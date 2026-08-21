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
