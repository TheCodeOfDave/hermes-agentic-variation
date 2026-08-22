from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from phase4_patch import ValidatedPatch

_ALLOWED = ("calculator.py", "test_calculator.py")
_COMMAND_ID = "phase4.python-unittest.v1"
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


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for relative in _ALLOWED:
        payload = (root / relative).read_bytes()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(payload).digest())
    return digest.hexdigest()


def main() -> int:
    input_root = Path("/input")
    work_root = Path("/work")
    patch_path = Path("/patch/input.patch")
    for relative in _ALLOWED:
        source = input_root / relative
        if source.is_symlink() or not source.is_file() or source.stat().st_size > 16384:
            raise ValueError("invalid baseline input")
        (work_root / relative).write_bytes(source.read_bytes())
    patch = ValidatedPatch.parse(patch_path.read_text(encoding="utf-8"))
    baseline = (work_root / "calculator.py").read_text(encoding="utf-8")
    candidate = patch.apply(baseline)
    (work_root / "calculator.py").write_text(candidate, encoding="utf-8", newline="\n")
    completed = subprocess.run(
        [sys.executable, "-m", "unittest", "-q"],
        cwd=work_root,
        env={"PYTHONIOENCODING": "utf-8", "PYTHONNOUSERSITE": "1"},
        shell=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
        check=False,
    )
    payload = {
        "candidate_source_b64": base64.b64encode(candidate.encode("utf-8")).decode("ascii"),
        "candidate_source_hash": hashlib.sha256(candidate.encode("utf-8")).hexdigest(),
        "candidate_tree_hash": _tree_hash(work_root),
        "command_id": _COMMAND_ID,
        "exit_code": int(completed.returncode),
        "tests_passed": completed.returncode == 0,
        "stdout_hash": hashlib.sha256(completed.stdout).hexdigest(),
        "stderr_hash": hashlib.sha256(completed.stderr).hexdigest(),
        "policy": _POLICY,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > 65536:
        raise ValueError("sandbox output is oversized")
    os.write(1, encoded.encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
