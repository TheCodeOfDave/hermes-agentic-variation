from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from .phase5_patch import ALLOWLIST, ValidatedPatchSet
    from .phase5_stage_a import (
        COMMAND_ID as APPLIER_COMMAND_ID,
        POLICY as STAGE_A_POLICY,
        build_manifest,
        tree_hash,
    )
except ImportError:  # Direct module execution in local tests.
    from phase5_patch import ALLOWLIST, ValidatedPatchSet
    from phase5_stage_a import (
        COMMAND_ID as APPLIER_COMMAND_ID,
        POLICY as STAGE_A_POLICY,
        build_manifest,
        tree_hash,
    )

STAGE_A_STDOUT_LIMIT = 96 * 1024
STAGE_B_STDOUT_LIMIT = 4 * 1024
WORKER_PIPE_LIMIT = 64 * 1024
SUCCESS_TRAILER = b"PHASE5_EVALUATOR_PASS cases=2\n"
_EXPECTED_A = {
    "changed_paths",
    "sources_b64",
    "source_hashes",
    "candidate_tree_hash",
    "command_id",
    "status",
    "policy",
}


class Phase5SandboxViolation(ValueError):
    pass


class Phase5SandboxUnavailable(RuntimeError):
    pass


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")


def validate_stage_a_envelope(
    stdout: bytes, stderr: bytes, patchset: ValidatedPatchSet, baselines: dict[str, str]
) -> dict[str, str]:
    if stderr or not stdout or len(stdout) > STAGE_A_STDOUT_LIMIT:
        raise Phase5SandboxViolation("Stage A stderr, empty output, or overflow")
    try:
        payload = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Phase5SandboxViolation("Stage A envelope is not strict JSON") from exc
    if _canonical(payload) != stdout:
        raise Phase5SandboxViolation(
            "Stage A envelope has prefix, suffix, duplicate, or noncanonical framing"
        )
    if not isinstance(payload, dict) or set(payload) != _EXPECTED_A:
        raise Phase5SandboxViolation("Stage A envelope schema mismatch")
    if (
        payload["changed_paths"] != list(patchset.paths)
        or payload["command_id"] != APPLIER_COMMAND_ID
        or payload["status"] != "applied"
        or payload["policy"] != STAGE_A_POLICY
    ):
        raise Phase5SandboxViolation("Stage A path, command, status, or policy mismatch")
    expected = patchset.apply(baselines)
    if not isinstance(payload["sources_b64"], dict) or tuple(payload["sources_b64"]) != ALLOWLIST:
        raise Phase5SandboxViolation("Stage A source order mismatch")
    reconstructed: dict[str, str] = {}
    for path in ALLOWLIST:
        try:
            raw = base64.b64decode(payload["sources_b64"][path], validate=True)
            source = raw.decode("utf-8")
        except (KeyError, ValueError, UnicodeDecodeError) as exc:
            raise Phase5SandboxViolation("Stage A source encoding mismatch") from exc
        if source != expected[path] or payload["source_hashes"].get(path) != _sha(raw):
            raise Phase5SandboxViolation("Stage A host reconstruction mismatch")
        reconstructed[path] = source
    if payload["candidate_tree_hash"] != tree_hash(reconstructed):
        raise Phase5SandboxViolation("Stage A candidate tree mismatch")
    return reconstructed


def atomic_stage(root: str | Path, run_id: str, sources: dict[str, str]) -> Path:
    if re.fullmatch(r"phase5-[0-9a-f]{6,32}", run_id) is None or tuple(sources) != ALLOWLIST:
        raise Phase5SandboxViolation("staging identity or path order is invalid")
    root_path = Path(root).resolve()
    root_path.mkdir(parents=True, exist_ok=True)
    target = root_path / run_id
    staging = root_path / f".{run_id}.staging-{os.getpid()}"
    if target.exists() or staging.exists():
        raise Phase5SandboxViolation("candidate staging target already exists")
    staging.mkdir()
    try:
        for path in ALLOWLIST:
            (staging / path).write_text(sources[path], encoding="utf-8", newline="\n")
        os.replace(staging, target)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return target


@dataclass(frozen=True)
class StageBResult:
    eligible: bool
    classification: str
    exit_code: int | None
    stdout_hash: str
    stderr_hash: str
    trailer_matched: bool


def classify_stage_b(
    exit_code: int | None,
    stdout: bytes,
    stderr: bytes,
    *,
    timed_out: bool = False,
    overflow: bool = False,
) -> StageBResult:
    classification = "PASS"
    if timed_out:
        classification = "TIMEOUT"
    elif overflow or len(stdout) > STAGE_B_STDOUT_LIMIT or len(stderr) > WORKER_PIPE_LIMIT:
        classification = "OUTPUT_OVERFLOW"
    elif stderr:
        classification = "EVALUATOR_STDERR"
    elif exit_code != 0:
        classification = "EVALUATOR_EXIT"
    elif stdout != SUCCESS_TRAILER:
        classification = "FALSE_PASS"
    eligible = classification == "PASS"
    return StageBResult(
        eligible, classification, exit_code, _sha(stdout), _sha(stderr), stdout == SUCCESS_TRAILER
    )


def verify_candidate_identity(
    patchset: ValidatedPatchSet,
    baselines: dict[str, str],
    outputs: dict[str, str],
    expected_tree_hash: str | None,
) -> dict[str, Any]:
    if tuple(outputs) != ALLOWLIST or tuple(baselines) != ALLOWLIST:
        raise Phase5SandboxViolation("candidate source path order mismatch")
    changed = tuple(path for path in ALLOWLIST if outputs[path] != baselines[path])
    if changed != patchset.paths or outputs != patchset.apply(baselines):
        raise Phase5SandboxViolation("candidate changed-path or byte identity mismatch")
    candidate_tree = tree_hash(outputs)
    if expected_tree_hash is not None and candidate_tree != expected_tree_hash:
        raise Phase5SandboxViolation("candidate tree identity mismatch")
    return {
        "changed_paths": list(changed),
        "candidate_tree_hash": candidate_tree,
        "source_hashes": {p: _sha(outputs[p].encode("utf-8")) for p in ALLOWLIST},
    }


def find_inert_orphans(
    artifact_roots: str | Path | tuple[str | Path, ...], committed_run_ids: set[str]
) -> list[Path]:
    roots = artifact_roots if isinstance(artifact_roots, tuple) else (artifact_roots,)
    orphans: list[Path] = []
    for artifact_root in roots:
        root = Path(artifact_root).resolve()
        if not root.exists():
            continue
        for path in root.iterdir():
            staging = re.fullmatch(r"\.(phase5-[0-9a-f]{6,32})\.staging-[0-9]+", path.name)
            published = re.fullmatch(r"phase5-[0-9a-f]{6,32}", path.name)
            run_id = staging.group(1) if staging else path.name if published else None
            if path.is_dir() and run_id is not None and run_id not in committed_run_ids:
                orphans.append(path)
    return sorted(orphans, key=lambda path: str(path).encode("utf-8"))


@dataclass(frozen=True)
class Phase5ExecutionResult:
    sources: dict[str, str]
    candidate_tree_hash: str
    artifact_path: Path
    image: str
    trusted_applier_hash: str
    immutable_cases_hash: str
    evaluator_hash: str
    worker_bootstrap_hash: str
    policy_hash: str
    stage_a_envelope_hash: str
    stage_a_stderr_hash: str
    stage_b: StageBResult


DEFAULT_PHASE5_IMAGE = (
    "python:3.13-alpine@sha256:540c7d91f98ff6880174c40e99067bf5941eb54d818a7a5e094d188b196a934d"
)


class Phase5DockerSandbox:
    def __init__(
        self,
        runtime_root: str | Path,
        *,
        docker_executable: str | None = None,
        image: str = DEFAULT_PHASE5_IMAGE,
        timeout_seconds: int = 30,
    ) -> None:
        self.runtime_root = Path(runtime_root).resolve()
        self.source_root = Path(__file__).resolve().parent
        executable = docker_executable or shutil.which("docker")
        if not executable:
            raise Phase5SandboxUnavailable("Docker CLI is unavailable")
        self.docker_executable = str(Path(executable).resolve())
        if re.fullmatch(r"[^@]+@sha256:[0-9a-f]{64}", image) is None:
            raise Phase5SandboxViolation("image must be digest pinned")
        if type(timeout_seconds) is not int or not 5 <= timeout_seconds <= 120:
            raise Phase5SandboxViolation("timeout must be 5..120 seconds")
        self.image = image
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _file_hash(path: Path) -> str:
        return _sha(path.read_bytes())

    @property
    def trusted_applier_hash(self) -> str:
        return _sha(
            b"".join(
                p.name.encode() + b"\0" + bytes.fromhex(self._file_hash(p))
                for p in (
                    self.source_root / "phase5_stage_a.py",
                    self.source_root / "phase5_patch.py",
                )
            )
        )

    @property
    def evaluator_hash(self) -> str:
        return self._file_hash(self.source_root / "phase5_evaluator.py")

    @property
    def worker_bootstrap_hash(self) -> str:
        return self._file_hash(self.source_root / "phase5_worker.py")

    def _policy(self) -> dict[str, Any]:
        return {
            "network": "none",
            "read_only_root": True,
            "cap_drop": "ALL",
            "no_new_privileges": True,
            "memory_mib": 64,
            "cpus": 0.5,
            "pids_limit": 64,
            "user": "65534:65534",
            "tmpfs_bytes": 16777216,
            "stage_a_stdout_bytes": STAGE_A_STDOUT_LIMIT,
            "stage_b_stdout_bytes": STAGE_B_STDOUT_LIMIT,
            "worker_pipe_bytes": WORKER_PIPE_LIMIT,
            "stage_a_timeout_seconds": self.timeout_seconds,
            "stage_b_timeout_seconds": self.timeout_seconds,
            "stage_a_command_id": "phase5.trusted-applier.v1",
            "stage_b_command_id": "phase5.immutable-evaluator.v1",
        }

    def preflight(self) -> dict[str, Any]:
        self._verify_image()
        policy = self._policy()
        return {
            "image": self.image,
            "trusted_applier_hash": self.trusted_applier_hash,
            "evaluator_hash": self.evaluator_hash,
            "worker_bootstrap_hash": self.worker_bootstrap_hash,
            "policy_hash": _sha(_canonical(policy)),
            "stage_a_command_id": "phase5.trusted-applier.v1",
            "stage_b_command_id": "phase5.immutable-evaluator.v1",
            "policy": policy,
        }

    def _container_argv(self, stage: str, mounts: list[tuple[Path, str]]) -> list[str]:
        if stage not in {"stage-a", "stage-b"}:
            raise Phase5SandboxViolation("unknown stage")
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
        ]
        for source, target in mounts:
            argv += ["--mount", f"type=bind,src={source.resolve()},dst={target},readonly"]
        argv += [
            "--tmpfs",
            "/work:rw,nosuid,nodev,size=16777216,mode=1777",
            "--workdir=/work",
            self.image,
        ]
        argv += (
            ["python", "/runner/phase5_stage_a.py"]
            if stage == "stage-a"
            else ["python", "/evaluator/phase5_evaluator.py"]
        )
        return argv

    def run(
        self,
        run_id: str,
        baseline_dir: str | Path,
        patchset: ValidatedPatchSet,
        artifact_root: str | Path,
    ) -> Phase5ExecutionResult:
        if re.fullmatch(r"phase5-[0-9a-f]{6,32}", run_id) is None:
            raise Phase5SandboxViolation("run_id is not a Variation Cycle identifier")
        facts = self.preflight()
        baseline = Path(baseline_dir).resolve()
        baselines = {p: (baseline / p).read_text(encoding="utf-8") for p in ALLOWLIST}
        verify_candidate_identity(patchset, baselines, patchset.apply(baselines), None)
        input_dir = self.runtime_root / "inputs" / run_id
        input_dir.mkdir(parents=True, exist_ok=False)
        manifest = build_manifest(patchset, baselines)
        (input_dir / "manifest.json").write_bytes(_canonical(manifest))
        a_argv = self._container_argv(
            "stage-a",
            [(input_dir, "/input"), (baseline, "/baseline"), (self.source_root, "/runner")],
        )
        a_exit, a_out, a_err, a_timeout, a_overflow = self._run_bounded(
            a_argv, STAGE_A_STDOUT_LIMIT, 65536
        )
        if a_timeout or a_overflow or a_exit != 0:
            raise Phase5SandboxViolation("Stage A process failed, timed out, or overflowed")
        outputs = validate_stage_a_envelope(a_out, a_err, patchset, baselines)
        verify_candidate_identity(patchset, baselines, outputs, tree_hash(outputs))
        staged = atomic_stage(self.runtime_root / "candidates", run_id, outputs)
        immutable = baseline.parent / f"{run_id}-immutable"
        cases = immutable / "phase5_cases.json"
        if not cases.is_file():
            raise Phase5SandboxViolation("immutable case corpus missing")
        evaluator_dir = input_dir / "evaluator"
        evaluator_dir.mkdir()
        shutil.copyfile(cases, evaluator_dir / "phase5_cases.json")
        shutil.copyfile(
            self.source_root / "phase5_evaluator.py", evaluator_dir / "phase5_evaluator.py"
        )
        shutil.copyfile(self.source_root / "phase5_worker.py", evaluator_dir / "phase5_worker.py")
        b_argv = self._container_argv(
            "stage-b", [(staged, "/candidate"), (evaluator_dir, "/evaluator")]
        )
        b_exit, b_out, b_err, b_timeout, b_overflow = self._run_bounded(
            b_argv, STAGE_B_STDOUT_LIMIT, 65536
        )
        stage_b = classify_stage_b(b_exit, b_out, b_err, timed_out=b_timeout, overflow=b_overflow)
        final_root = Path(artifact_root).resolve()
        final_root.mkdir(parents=True, exist_ok=True)
        final = atomic_stage(final_root, run_id, outputs)
        return Phase5ExecutionResult(
            outputs,
            tree_hash(outputs),
            final,
            self.image,
            self.trusted_applier_hash,
            _sha(cases.read_bytes()),
            self.evaluator_hash,
            self.worker_bootstrap_hash,
            facts["policy_hash"],
            _sha(a_out),
            _sha(a_err),
            stage_b,
        )

    def _verify_image(self) -> None:
        code, out, err, timed, overflow = self._run_bounded(
            [
                self.docker_executable,
                "image",
                "inspect",
                "--format",
                "{{json .RepoDigests}}",
                self.image,
            ],
            65536,
            65536,
            20,
        )
        if code != 0 or timed or overflow or err:
            raise Phase5SandboxUnavailable("pinned image is unavailable")
        try:
            digests = json.loads(out.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise Phase5SandboxUnavailable("image inspection failed") from exc
        expected = self.image.split("@", 1)[1]
        if not isinstance(digests, list) or not any(
            isinstance(x, str) and x.endswith("@" + expected) for x in digests
        ):
            raise Phase5SandboxUnavailable("local image digest mismatch")

    def _run_bounded(
        self, argv: list[str], stdout_limit: int, stderr_limit: int, timeout: int | None = None
    ) -> tuple[int | None, bytes, bytes, bool, bool]:
        env = {
            "DOCKER_CONFIG": str(self.runtime_root / "docker-config"),
            "PATH": str(Path(self.docker_executable).parent),
        }
        Path(env["DOCKER_CONFIG"]).mkdir(parents=True, exist_ok=True)
        for name in ("SYSTEMROOT", "WINDIR", "DOCKER_HOST"):
            if os.environ.get(name):
                env[name] = os.environ[name]
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            env=env,
        )
        buffers = {"stdout": bytearray(), "stderr": bytearray()}
        overflow = threading.Event()

        def read(name, stream, limit):
            while True:
                chunk = stream.read(8192)
                if not chunk:
                    break
                buffers[name].extend(chunk)
                if len(buffers[name]) > limit:
                    overflow.set()
                    try:
                        proc.kill()
                    except OSError:
                        pass
                    break

        threads = [
            threading.Thread(target=read, args=("stdout", proc.stdout, stdout_limit), daemon=True),
            threading.Thread(target=read, args=("stderr", proc.stderr, stderr_limit), daemon=True),
        ]
        for thread in threads:
            thread.start()
        timed = False
        try:
            code = proc.wait(timeout=timeout or self.timeout_seconds)
        except subprocess.TimeoutExpired:
            timed = True
            proc.kill()
            code = proc.wait()
        for thread in threads:
            thread.join(timeout=2)
        return code, bytes(buffers["stdout"]), bytes(buffers["stderr"]), timed, overflow.is_set()
