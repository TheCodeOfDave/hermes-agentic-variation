from __future__ import annotations

import base64
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

try:
    from .phase5_patch import ALLOWLIST, ValidatedPatchSet
except ImportError:  # Direct module execution in local tests.
    from phase5_patch import ALLOWLIST, ValidatedPatchSet

COMMAND_ID = "phase5.trusted-applier.v1"
POLICY = {
    "network": "none",
    "read_only_root": True,
    "cap_drop": "ALL",
    "no_new_privileges": True,
    "memory_mib": 64,
    "cpus": 0.5,
    "pids_limit": 64,
    "user": "65534:65534",
    "tmpfs_bytes": 16777216,
    "stdout_bytes": 98304,
    "stderr_bytes": 65536,
    "timeout_seconds": 30,
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")


def tree_hash(sources: dict[str, str]) -> str:
    pairs = [[path, _sha(sources[path].encode("utf-8"))] for path in ALLOWLIST]
    return _sha(_canonical(pairs))


def build_manifest(patchset: ValidatedPatchSet, baselines: dict[str, str]) -> dict[str, Any]:
    if tuple(sorted(baselines, key=lambda p: p.encode("utf-8"))) != ALLOWLIST:
        raise ValueError("baseline path set is invalid")
    return {
        "baseline_hashes": {p: _sha(baselines[p].encode("utf-8")) for p in ALLOWLIST},
        "baseline_sources_b64": {
            p: base64.b64encode(baselines[p].encode()).decode("ascii") for p in ALLOWLIST
        },
        "patch_set_hash": patchset.identity,
        "patches": [{"path": m.path, "patch": m.raw} for m in patchset.members],
        "rationale": patchset.rationale,
        "command_id": COMMAND_ID,
        "policy": dict(POLICY),
    }


def apply_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    required = {
        "baseline_hashes",
        "baseline_sources_b64",
        "patch_set_hash",
        "patches",
        "rationale",
        "command_id",
        "policy",
    }
    if not isinstance(manifest, dict) or set(manifest) != required:
        raise ValueError("manifest schema is invalid")
    if manifest["command_id"] != COMMAND_ID or manifest["policy"] != POLICY:
        raise ValueError("command or policy identity mismatch")
    if (
        not isinstance(manifest["baseline_hashes"], dict)
        or tuple(manifest["baseline_hashes"]) != ALLOWLIST
    ):
        raise ValueError("baseline path order is invalid")
    sources: dict[str, str] = {}
    for path in ALLOWLIST:
        try:
            raw = base64.b64decode(manifest["baseline_sources_b64"][path], validate=True)
            source = raw.decode("utf-8")
        except (KeyError, ValueError, UnicodeDecodeError) as exc:
            raise ValueError("baseline encoding is invalid") from exc
        if _sha(raw) != manifest["baseline_hashes"].get(path):
            raise ValueError("baseline hash mismatch")
        if (
            source.startswith("\ufeff")
            or "\r" in source
            or not source.endswith("\n")
            or len(raw) > 16384
        ):
            raise ValueError("baseline source is invalid")
        sources[path] = source
    raw_set = json.dumps(
        {"patches": manifest["patches"], "rationale": manifest["rationale"]},
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    patchset = ValidatedPatchSet.parse(raw_set)
    if patchset.identity != manifest["patch_set_hash"]:
        raise ValueError("patch-set identity mismatch")
    outputs = patchset.apply(sources)
    source_hashes = {p: _sha(outputs[p].encode("utf-8")) for p in ALLOWLIST}
    return {
        "changed_paths": list(patchset.paths),
        "sources_b64": {
            p: base64.b64encode(outputs[p].encode()).decode("ascii") for p in ALLOWLIST
        },
        "source_hashes": source_hashes,
        "candidate_tree_hash": tree_hash(outputs),
        "command_id": COMMAND_ID,
        "status": "applied",
        "policy": dict(POLICY),
    }


def main() -> int:
    raw = Path("/input/manifest.json").read_bytes()
    if len(raw) > 131072:
        raise ValueError("manifest exceeds input ceiling")
    manifest = json.loads(raw.decode("utf-8"))
    for path in ALLOWLIST:
        baseline = Path("/baseline") / path
        if (
            not baseline.is_file()
            or baseline.is_symlink()
            or hashlib.sha256(baseline.read_bytes()).hexdigest()
            != manifest.get("baseline_hashes", {}).get(path)
        ):
            raise ValueError("mounted baseline identity mismatch")
    encoded = _canonical(apply_manifest(manifest))
    if len(encoded) > POLICY["stdout_bytes"]:
        raise ValueError("applier envelope overflow")
    sys.stdout.buffer.write(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
