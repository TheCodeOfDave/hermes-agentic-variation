from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from phase3_workspace import Phase3Workspace, WorkspaceViolation


def test_workspace_creates_real_no_commit_no_remote_git_fixture(tmp_path):
    workspace = Phase3Workspace(tmp_path / "runs", test_timeout_seconds=10)

    repo = workspace.create("phase3-abcdef")

    assert repo.parent == (tmp_path / "runs").resolve()
    assert (repo / ".git").is_dir()
    assert (repo / "calculator.py").read_text(encoding="utf-8").endswith(
        "    return sum(numbers)\n"
    )
    assert workspace.git_facts(repo) == {"commit_count": 0, "remotes": []}


def test_fixed_executor_passes_only_filter_even(tmp_path):
    workspace = Phase3Workspace(tmp_path / "runs", test_timeout_seconds=10)
    results = {}

    for suffix, mutation in (
        ("aaaaaa", "baseline"),
        ("bbbbbb", "filter_odd"),
        ("cccccc", "filter_even"),
    ):
        repo = workspace.create(f"phase3-{suffix}")
        baseline_hash = workspace.tree_hash(repo)
        changed = workspace.apply(repo, mutation)
        result = workspace.evaluate(repo)
        results[mutation] = (baseline_hash, workspace.tree_hash(repo), changed, result)

    assert results["baseline"][2] == ()
    assert results["baseline"][3].tests_passed is False
    assert results["filter_odd"][2] == ("calculator.py",)
    assert results["filter_odd"][3].tests_passed is False
    assert results["filter_even"][2] == ("calculator.py",)
    assert results["filter_even"][3].tests_passed is True
    assert results["filter_even"][3].argv == ("python", "-m", "unittest", "-q")
    assert results["filter_even"][0] != results["filter_even"][1]


def test_workspace_rejects_untrusted_identifiers_and_unknown_mutations(tmp_path):
    workspace = Phase3Workspace(tmp_path / "runs", test_timeout_seconds=10)

    for invalid in ("../escape", "phase2-abcdef", "phase3-ABCDEF", "phase3-aa"):
        with pytest.raises(WorkspaceViolation):
            workspace.create(invalid)

    repo = workspace.create("phase3-abcdef")
    with pytest.raises(WorkspaceViolation, match="mutation"):
        workspace.apply(repo, "model-authored-code")


def test_executor_uses_no_shell_and_fixed_cwd(tmp_path, monkeypatch):
    workspace = Phase3Workspace(tmp_path / "runs", test_timeout_seconds=7)
    repo = workspace.create("phase3-abcdef")
    real_run = subprocess.run
    calls = []

    def observed_run(*args, **kwargs):
        calls.append((args, kwargs))
        return real_run(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", observed_run)
    result = workspace.evaluate(repo)

    assert result.tests_passed is False
    args, kwargs = calls[-1]
    assert args[0][1:] == ["-m", "unittest", "-q"]
    assert kwargs["cwd"] == repo
    assert kwargs["shell"] is False
    assert kwargs["timeout"] == 7
    assert kwargs["env"] == {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONNOUSERSITE": "1",
    }


def test_git_commands_use_absolute_executable_and_isolated_config(tmp_path, monkeypatch):
    real_run = subprocess.run
    calls = []

    def observed_run(*args, **kwargs):
        calls.append((args, kwargs))
        return real_run(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", observed_run)
    workspace = Phase3Workspace(tmp_path / "runs", test_timeout_seconds=10)
    repo = workspace.create("phase3-abcdef")
    workspace.git_facts(repo)
    git_calls = [call for call in calls if "git" in str(call[0][0][0]).lower()]

    assert len(git_calls) == 3
    for args, kwargs in git_calls:
        assert Path(args[0][0]).is_absolute()
        assert kwargs["shell"] is False
        assert kwargs["env"]["GIT_CONFIG_NOSYSTEM"] == "1"
        assert kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"
        assert kwargs["env"]["HOME"] == str(repo)


def test_git_failure_is_sanitized_as_workspace_violation(tmp_path, monkeypatch):
    workspace = Phase3Workspace(tmp_path / "runs", test_timeout_seconds=10)

    def failed_run(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0], stderr=b"private path details")

    monkeypatch.setattr(subprocess, "run", failed_run)

    with pytest.raises(WorkspaceViolation, match="fixed git command failed") as error:
        workspace.create("phase3-abcdef")
    assert "private path" not in str(error.value)


def test_test_timeout_is_fail_closed_and_hashed(tmp_path, monkeypatch):
    workspace = Phase3Workspace(tmp_path / "runs", test_timeout_seconds=4)
    repo = workspace.create("phase3-abcdef")

    def timed_out(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"], output=b"partial")

    monkeypatch.setattr(subprocess, "run", timed_out)

    result = workspace.evaluate(repo)

    assert result.exit_code == 124
    assert result.tests_passed is False
    assert result.stdout == b"partial"
    assert b"PHASE3_TEST_TIMEOUT" in result.stderr
    assert len(result.stderr_hash) == 64
