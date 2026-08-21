from __future__ import annotations

from types import SimpleNamespace

from runtime import HermesLifecycleAdapter


class FakeService:
    def __init__(self, *, timed_out=False, result=None):
        self.timed_out = timed_out
        self.result_value = result
        self.launched = []
        self.cancelled = []

    def launch(self, request):
        self.launched.append(request)
        return {"handle": 1}

    def wait(self, handle, *, timeout_seconds):
        return SimpleNamespace(timed_out=self.timed_out)

    def cancel(self, handle, *, reason):
        self.cancelled.append((handle, reason))
        return SimpleNamespace(accepted=True)

    def result(self, handle):
        return self.result_value


def request_factory(**kwargs):
    return kwargs


def test_runtime_adapter_launches_no_tool_child_and_normalizes_success():
    service = FakeService(
        result=SimpleNamespace(
            terminal_state=SimpleNamespace(value="SUCCEEDED"),
            summary='{"strategy":"single_pass","rationale":"bounded"}',
            result_hash="a" * 64,
            usage_metadata={"api_calls": 1},
            error_message=None,
        )
    )
    adapter = HermesLifecycleAdapter(service, request_factory=request_factory)

    result = adapter.run(
        goal="goal",
        context="context",
        role="leaf",
        correlation_id="run:1",
        allowed_toolsets=("todo",),
        wait_seconds=12,
    )

    assert service.launched == [
        {
            "goal": "goal",
            "context": "context",
            "role": "leaf",
            "correlation_id": "run:1",
            "allowed_toolsets": ("todo",),
            "metadata": {"plugin": "agentic-variation", "phase": 1},
        }
    ]
    assert result.terminal_state == "SUCCEEDED"
    assert result.result_hash == "a" * 64
    assert result.api_calls == 1


def test_runtime_adapter_cancels_timeout_and_returns_failure():
    service = FakeService(timed_out=True, result=None)
    adapter = HermesLifecycleAdapter(service, request_factory=request_factory)

    result = adapter.run(
        goal="goal",
        context="context",
        role="leaf",
        correlation_id="run:2",
        allowed_toolsets=("todo",),
        wait_seconds=3,
    )

    assert result.terminal_state == "FAILED"
    assert result.error == "CHILD_TIMEOUT"
    assert len(service.cancelled) == 1
    assert len(result.result_hash) == 64


def test_runtime_adapter_labels_phase2_metadata_and_timeout():
    service = FakeService(timed_out=True, result=None)
    adapter = HermesLifecycleAdapter(service, request_factory=request_factory, phase=2)

    adapter.run(
        goal="goal",
        context="context",
        role="leaf",
        correlation_id="run:phase2",
        allowed_toolsets=("todo",),
        wait_seconds=3,
    )

    assert service.launched[0]["metadata"]["phase"] == 2
    assert "Phase 2" in service.cancelled[0][1]
