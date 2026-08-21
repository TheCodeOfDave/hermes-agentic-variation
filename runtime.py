from __future__ import annotations

import hashlib
from typing import Any, Callable

try:
    from .controller import ChildOutcome
except ImportError:  # Direct module execution in local tests.
    from controller import ChildOutcome


class HermesLifecycleAdapter:
    """Narrow adapter over Hermes' public subagent lifecycle service."""

    def __init__(self, service: Any, *, request_factory: Callable[..., Any] | None = None):
        self.service = service
        self.request_factory = request_factory

    def _request(self, **kwargs: Any) -> Any:
        factory = self.request_factory
        if factory is None:
            from agent.subagent_lifecycle import SubagentLaunchRequest

            factory = SubagentLaunchRequest
        return factory(**kwargs)

    def run(
        self,
        *,
        goal: str,
        context: str,
        role: str,
        correlation_id: str,
        allowed_toolsets: tuple[str, ...],
        wait_seconds: int,
    ) -> ChildOutcome:
        request = self._request(
            goal=goal,
            context=context,
            role=role,
            correlation_id=correlation_id,
            allowed_toolsets=allowed_toolsets,
            metadata={"plugin": "agentic-variation", "phase": 1},
        )
        handle = self.service.launch(request)
        terminal = self.service.wait(handle, timeout_seconds=wait_seconds)
        if terminal.timed_out:
            self.service.cancel(handle, reason="Agentic Variation Phase 1 wait budget expired")
            digest = hashlib.sha256(f"timeout:{correlation_id}".encode("utf-8")).hexdigest()
            return ChildOutcome(
                terminal_state="FAILED",
                summary=None,
                result_hash=digest,
                api_calls=0,
                error="CHILD_TIMEOUT",
            )

        result = self.service.result(handle)
        state_value = getattr(result.terminal_state, "value", result.terminal_state)
        summary = result.summary if isinstance(result.summary, str) else None
        result_hash = result.result_hash
        if not isinstance(result_hash, str) or len(result_hash) != 64:
            material = f"{state_value}:{summary or ''}:{result.error_message or ''}"
            result_hash = hashlib.sha256(material.encode("utf-8")).hexdigest()
        usage = result.usage_metadata if isinstance(result.usage_metadata, dict) else {}
        api_calls = usage.get("api_calls", 0)
        if type(api_calls) is not int or api_calls < 0:
            api_calls = 0
        return ChildOutcome(
            terminal_state=str(state_value),
            summary=summary,
            result_hash=result_hash,
            api_calls=api_calls,
            error=result.error_message,
        )
