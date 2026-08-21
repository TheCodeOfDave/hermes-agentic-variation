"""Hermes Agentic Variation plugin registration."""

try:
    from . import schemas, tools
except ImportError:  # Pytest can collect a repository-root plugin as top-level __init__.
    import schemas
    import tools


def register(ctx):
    """Register Phase 0's read-only contract inspection tools."""
    ctx.register_tool(
        name="avo_phase0_info",
        toolset="agentic-variation",
        schema=schemas.AVO_PHASE0_INFO,
        handler=tools.avo_phase0_info,
    )
    ctx.register_tool(
        name="avo_validate_run_spec",
        toolset="agentic-variation",
        schema=schemas.AVO_VALIDATE_RUN_SPEC,
        handler=tools.avo_validate_run_spec,
    )
