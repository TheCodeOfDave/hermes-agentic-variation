from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

try:
    from .phase4_patch import ValidatedPatch
except ImportError:
    from phase4_patch import ValidatedPatch

DEFAULT_IMAGE = (
    "python:3.13-alpine@sha256:"
    "540c7d91f98ff6880174c40e99067bf5941eb54d818a7a5e094d188b196a934d"
)
_POLICY = {
    "network": "none",
    "read_only_root": True,
    "cap_drop": "ALL",
    "no_new_privileges": True,
    "memory_mib": 64,
    "cpus": 0.5,
    "pids_limit": 64,
    "user": "65534:65534",
    "tmpfs_bytes": 16777216,
}
_EXPECTED_KEYS = {
    "candidate_source_b64",
    "candidate_source_hash",
    "candidate_tree_hash",
    "command_id",
    "exit_code",
    "tests_passed",
    "stdout_hash",
    "stderr_hash",
    "policy",
}


class SandboxUnavailable(RuntimeError):
    """The pinned Docker sandbox runtime is not available."""


class SandboxViolation(ValueError):
    """Sandbox input/output violated the fixed Phase 4 contract."""


@dataclass(frozen=True)
class SandboxResult:
    candidate_source: str
    candidate_source_hash: str
    candidate_tree_hash: str
    command_id: str
    exit_code: int
    tests_passed: bool
    stdout_hash: str
    stderr_hash: str
    policy: dict[str, object]
    patch_hash: str
    patch_path: Path
    image: str
    runner_hash: str


class DockerSandbox:
    """Run one validated patch in a pinned, networkless Docker container."""

    def __init__(
        self,
        runtime_root: str | Path,
        *,
        docker_executable: str | None = None,
        image: str = DEFAULT_IMAGE,
        timeout_seconds: int = 30,
    ) -> None:
        self.runtime_root = Path(runtime_root).resolve()
        executable = docker_executable or shutil.which("docker")
        if not executable:
            raise SandboxUnavailable("Docker CLI is unavailable")
        self.docker_executable = str(Path(executable).resolve())
        if re.fullmatch(r"[^@]+@sha256:[0-9a-f]{64}", image) is None:
            raise SandboxViolation("sandbox image must be pinned by sha256 digest")
        if type(timeout_seconds) is not int or not 5 <= timeout_seconds <= 120:
            raise SandboxViolation("sandbox timeout must be an integer from 5 to 120")
        self.image = image
        self.timeout_seconds = timeout_seconds
        self.runner_root = Path(__file__).resolve().parent
        self.runner_path = self.runner_root / "phase4_runner.py"
        self.patch_module_path = self.runner_root / "phase4_patch.py"

    @property
    def runner_hash(self) -> str:
        digest = hashlib.sha256()
        for path in (self.runner_path, self.patch_module_path):
            digest.update(path.name.encode("utf-8"))
            digest.update(b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
        return digest.hexdigest()

    def run(
        self, run_id: str, baseline_dir: str | Path, patch: ValidatedPatch
    ) -> SandboxResult:
        if not isinstance(run_id, str) or re.fullmatch(r"phase4-[0-9a-f]{6,32}", run_id) is None:
            raise SandboxViolation("run_id is not a Phase 4 identifier")
        baseline = Path(baseline_dir).resolve()
        self._validate_baseline(baseline)
        self._verify_image()
        patch_dir = self.runtime_root / "phase4-inputs" / run_id
        patch_dir.mkdir(parents=True, exist_ok=False)
        patch_path = patch_dir / "input.patch"
        patch_path.write_text(patch.raw, encoding="utf-8", newline="\n")
        docker_config = self.runtime_root / "docker-config"
        docker_config.mkdir(parents=True, exist_ok=True)
        argv = [
            self.docker_executable,
            "run",
            "--rm",
            "--pull=never",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--memory=64m",
            "--cpus=0.5",
            "--pids-limit=64",
            "--user=65534:65534",
            "--mount",
            self._mount(baseline, "/input"),
            "--mount",
            self._mount(patch_dir, "/patch"),
            "--mount",
            self._mount(self.runner_root, "/runner"),
            "--tmpfs",
            "/work:rw,nosuid,nodev,size=16777216,mode=1777",
            "--workdir=/work",
            self.image,
            "python",
            "/runner/phase4_runner.py",
        ]
        completed = self._run(argv, docker_config=docker_config, timeout=self.timeout_seconds)
        if completed.returncode != 0:
            raise SandboxViolation("sandbox process failed")
        if len(completed.stdout) > 65536:
            raise SandboxViolation("sandbox output exceeds 65536 bytes")
        try:
            payload = json.loads(completed.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SandboxViolation("sandbox output is not valid JSON") from exc
        return self._validate_output(payload, baseline, patch, patch_path)

    def preflight(self) -> dict[str, object]:
        self._verify_image()
        return {
            "image": self.image,
            "runner_hash": self.runner_hash,
            "policy": dict(_POLICY),
        }

    def _verify_image(self) -> None:
        config = self.runtime_root / "docker-config"
        config.mkdir(parents=True, exist_ok=True)
        completed = self._run(
            [
                self.docker_executable,
                "image",
                "inspect",
                "--format",
                "{{json .RepoDigests}}",
                self.image,
            ],
            docker_config=config,
            timeout=20,
        )
        if completed.returncode != 0:
            raise SandboxUnavailable("pinned image is not available locally")
        try:
            digests = json.loads(completed.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SandboxUnavailable("pinned image inspection failed") from exc
        expected_digest = self.image.split("@", 1)[1]
        if not isinstance(digests, list) or not any(
            isinstance(item, str) and item.endswith("@" + expected_digest) for item in digests
        ):
            raise SandboxUnavailable("pinned image digest does not match local image")

    def _validate_output(
        self,
        payload: object,
        baseline: Path,
        patch: ValidatedPatch,
        patch_path: Path,
    ) -> SandboxResult:
        if not isinstance(payload, dict) or set(payload) != _EXPECTED_KEYS:
            raise SandboxViolation("sandbox output schema is invalid")
        if payload.get("policy") != _POLICY:
            raise SandboxViolation("sandbox policy receipt is invalid")
        try:
            candidate_bytes = base64.b64decode(
                payload["candidate_source_b64"], validate=True
            )
            candidate = candidate_bytes.decode("utf-8")
        except (KeyError, ValueError, UnicodeDecodeError) as exc:
            raise SandboxViolation("candidate source encoding is invalid") from exc
        if len(candidate_bytes) > 16384:
            raise SandboxViolation("candidate source is oversized")
        expected_source = patch.apply((baseline / "calculator.py").read_text(encoding="utf-8"))
        if candidate != expected_source:
            raise SandboxViolation("candidate source does not match validated patch")
        source_hash = hashlib.sha256(candidate_bytes).hexdigest()
        if payload.get("candidate_source_hash") != source_hash:
            raise SandboxViolation("candidate source hash is invalid")
        expected_tree = self._tree_hash(candidate_bytes, baseline)
        if payload.get("candidate_tree_hash") != expected_tree:
            raise SandboxViolation("candidate tree hash is invalid")
        for name in ("stdout_hash", "stderr_hash"):
            if re.fullmatch(r"[0-9a-f]{64}", str(payload.get(name))) is None:
                raise SandboxViolation(f"{name} is invalid")
        exit_code = payload.get("exit_code")
        tests_passed = payload.get("tests_passed")
        if type(exit_code) is not int or not isinstance(tests_passed, bool):
            raise SandboxViolation("sandbox test result types are invalid")
        if tests_passed != (exit_code == 0):
            raise SandboxViolation("sandbox test result is inconsistent")
        if payload.get("command_id") != "phase4.python-unittest.v1":
            raise SandboxViolation("sandbox command ID is invalid")
        return SandboxResult(
            candidate_source=candidate,
            candidate_source_hash=source_hash,
            candidate_tree_hash=expected_tree,
            command_id="phase4.python-unittest.v1",
            exit_code=exit_code,
            tests_passed=tests_passed,
            stdout_hash=str(payload["stdout_hash"]),
            stderr_hash=str(payload["stderr_hash"]),
            policy=dict(_POLICY),
            patch_hash=patch.identity,
            patch_path=patch_path,
            image=self.image,
            runner_hash=self.runner_hash,
        )

    @staticmethod
    def _validate_baseline(baseline: Path) -> None:
        if baseline.is_symlink() or not baseline.is_dir():
            raise SandboxViolation("baseline directory is invalid")
        for name in ("calculator.py", "test_calculator.py"):
            path = baseline / name
            if path.is_symlink() or not path.is_file() or path.resolve().parent != baseline:
                raise SandboxViolation("baseline file is invalid")
            if path.stat().st_size > 16384:
                raise SandboxViolation("baseline file is oversized")

    @staticmethod
    def _mount(source: Path, target: str) -> str:
        return f"type=bind,src={source.resolve()},dst={target},readonly"

    def _run(
        self, argv: list[str], *, docker_config: Path, timeout: int
    ) -> subprocess.CompletedProcess[bytes]:
        env = {
            "DOCKER_CONFIG": str(docker_config),
            "PATH": str(Path(self.docker_executable).parent),
        }
        for name in ("SYSTEMROOT", "WINDIR", "DOCKER_HOST"):
            if os.environ.get(name):
                env[name] = os.environ[name]
        try:
            return subprocess.run(
                argv,
                env=env,
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise SandboxViolation("sandbox process timed out") from exc

    @staticmethod
    def _tree_hash(candidate: bytes, baseline: Path) -> str:
        digest = hashlib.sha256()
        for name, payload in (
            ("calculator.py", candidate),
            ("test_calculator.py", (baseline / "test_calculator.py").read_bytes()),
        ):
            digest.update(name.encode("utf-8"))
            digest.update(b"\0")
            digest.update(hashlib.sha256(payload).digest())
        return digest.hexdigest()
