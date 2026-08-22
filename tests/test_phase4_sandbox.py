from __future__ import annotations

import base64
import hashlib
import json
import subprocess


import pytest

from phase4_patch import ValidatedPatch
from phase4_sandbox import DockerSandbox, SandboxUnavailable, SandboxViolation

IMAGE = "python:3.13-alpine@sha256:540c7d91f98ff6880174c40e99067bf5941eb54d818a7a5e094d188b196a934d"
BASELINE = "def sum_even(numbers):\n    return sum(numbers)\n"
TEST = "import unittest\n"
PATCH = """--- a/calculator.py
+++ b/calculator.py
@@ -1,2 +1,2 @@
 def sum_even(numbers):
-    return sum(numbers)
+    return sum(number for number in numbers if number % 2 == 0)
"""


def tree_hash(calculator):
    digest = hashlib.sha256()
    for name, payload in (("calculator.py", calculator.encode()), ("test_calculator.py", TEST.encode())):
        digest.update(name.encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256(payload).digest())
    return digest.hexdigest()


def output_payload(candidate):
    return {
        "candidate_source_b64": base64.b64encode(candidate.encode()).decode(),
        "candidate_source_hash": hashlib.sha256(candidate.encode()).hexdigest(),
        "candidate_tree_hash": tree_hash(candidate),
        "command_id": "phase4.python-unittest.v1",
        "exit_code": 0,
        "tests_passed": True,
        "stdout_hash": hashlib.sha256(b"").hexdigest(),
        "stderr_hash": hashlib.sha256(b"ok").hexdigest(),
        "policy": {
            "network": "none",
            "read_only_root": True,
            "cap_drop": "ALL",
            "no_new_privileges": True,
            "memory_mib": 64,
            "cpus": 0.5,
            "pids_limit": 64,
            "user": "65534:65534",
            "tmpfs_bytes": 16777216,
        },
    }


def baseline_repo(tmp_path):
    repo = tmp_path / "baseline"
    repo.mkdir()
    (repo / "calculator.py").write_text(BASELINE, encoding="utf-8", newline="\n")
    (repo / "test_calculator.py").write_text(TEST, encoding="utf-8", newline="\n")
    return repo


def test_sandbox_uses_fixed_digest_policy_and_read_only_mounts(tmp_path, monkeypatch):
    repo = baseline_repo(tmp_path)
    candidate = ValidatedPatch.parse(PATCH).apply(BASELINE)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        if "inspect" in argv:
            return subprocess.CompletedProcess(argv, 0, (json.dumps([IMAGE]) + "\n").encode(), b"")
        return subprocess.CompletedProcess(
            argv, 0, json.dumps(output_payload(candidate), sort_keys=True).encode(), b""
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    sandbox = DockerSandbox(
        tmp_path / "runtime",
        docker_executable="C:/docker.exe",
        image=IMAGE,
        timeout_seconds=30,
    )

    result = sandbox.run("phase4-abcdef", repo, ValidatedPatch.parse(PATCH))

    run_argv, run_kwargs = calls[-1]
    assert run_argv[:4] == [sandbox.docker_executable, "run", "--rm", "--pull=never"]
    for required in (
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--memory=64m",
        "--cpus=0.5",
        "--pids-limit=64",
        "--user=65534:65534",
    ):
        assert required in run_argv
    mounts = [run_argv[index + 1] for index, value in enumerate(run_argv) if value == "--mount"]
    assert len(mounts) == 3
    assert all("readonly" in mount for mount in mounts)
    assert "--network=none" in run_argv
    assert run_kwargs["shell"] is False
    assert run_kwargs["stdin"] == subprocess.DEVNULL
    assert run_kwargs["timeout"] == 30
    assert result.candidate_source == candidate
    assert result.patch_hash == ValidatedPatch.parse(PATCH).identity
    assert result.tests_passed is True
    assert result.patch_path.is_file()


def test_sandbox_rejects_tampered_output(tmp_path, monkeypatch):
    repo = baseline_repo(tmp_path)
    candidate = ValidatedPatch.parse(PATCH).apply(BASELINE)
    payload = output_payload(candidate)
    payload["candidate_source_hash"] = "0" * 64

    def fake_run(argv, **kwargs):
        if "inspect" in argv:
            return subprocess.CompletedProcess(argv, 0, (json.dumps([IMAGE]) + "\n").encode(), b"")
        return subprocess.CompletedProcess(argv, 0, json.dumps(payload).encode(), b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    sandbox = DockerSandbox(tmp_path / "runtime", docker_executable="C:/docker.exe", image=IMAGE)

    with pytest.raises(SandboxViolation, match="source hash"):
        sandbox.run("phase4-abcdef", repo, ValidatedPatch.parse(PATCH))


def test_sandbox_fails_closed_when_pinned_image_is_unavailable(tmp_path, monkeypatch):
    repo = baseline_repo(tmp_path)

    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 1, b"", b"missing")

    monkeypatch.setattr(subprocess, "run", fake_run)
    sandbox = DockerSandbox(tmp_path / "runtime", docker_executable="C:/docker.exe", image=IMAGE)

    with pytest.raises(SandboxUnavailable, match="pinned image"):
        sandbox.run("phase4-abcdef", repo, ValidatedPatch.parse(PATCH))
