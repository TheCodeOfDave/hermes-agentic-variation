from __future__ import annotations

import json
import pytest

from phase5_fixture import SOURCES
from phase5_patch import ValidatedPatchSet
from test_phase5_patch import member


def patchset():
    return ValidatedPatchSet.parse(
        json.dumps(
            {"patches": [member("calculator.py"), member("filters.py")], "rationale": "stage a"}
        )
    )


def test_stage_a_applier_is_data_only_atomic_and_revalidates_baseline(tmp_path):
    from phase5_stage_a import apply_manifest, build_manifest

    baselines = dict(SOURCES)
    manifest = build_manifest(patchset(), baselines)
    envelope = apply_manifest(manifest)
    assert envelope["status"] == "applied"
    assert envelope["changed_paths"] == ["calculator.py", "filters.py"]
    assert list(envelope["sources_b64"]) == ["calculator.py", "filters.py", "formatting.py"]
    tampered = json.loads(json.dumps(manifest))
    tampered["baseline_hashes"]["calculator.py"] = "0" * 64
    with pytest.raises(ValueError, match="baseline"):
        apply_manifest(tampered)


def test_stage_a_all_or_nothing_when_late_member_is_invalid():
    from phase5_stage_a import apply_manifest, build_manifest

    ps = patchset()
    manifest = build_manifest(ps, dict(SOURCES))
    manifest["patches"][1]["patch"] = manifest["patches"][1]["patch"].replace(
        "value = 1", "missing"
    )
    with pytest.raises(ValueError):
        apply_manifest(manifest)


def test_stage_a_host_reconstruction_and_single_envelope_framing(tmp_path):
    from phase5_sandbox import Phase5SandboxViolation, validate_stage_a_envelope
    from phase5_stage_a import apply_manifest, build_manifest

    ps = patchset()
    baselines = dict(SOURCES)
    envelope = apply_manifest(build_manifest(ps, baselines))
    raw = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
    accepted = validate_stage_a_envelope(raw, b"", ps, baselines)
    assert accepted["calculator.py"] != baselines["calculator.py"]
    for forged in (b"", b"x" + raw, raw + b"x", raw + raw, raw[:-1]):
        with pytest.raises(Phase5SandboxViolation):
            validate_stage_a_envelope(forged, b"", ps, baselines)
    with pytest.raises(Phase5SandboxViolation):
        validate_stage_a_envelope(raw, b"stderr", ps, baselines)


def test_stage_a_host_rejects_forged_source_and_atomic_staging(tmp_path):
    from phase5_sandbox import Phase5SandboxViolation, atomic_stage, validate_stage_a_envelope
    from phase5_stage_a import apply_manifest, build_manifest

    ps = patchset()
    baselines = dict(SOURCES)
    envelope = apply_manifest(build_manifest(ps, baselines))
    envelope["sources_b64"]["calculator.py"] = envelope["sources_b64"]["filters.py"]
    raw = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(Phase5SandboxViolation):
        validate_stage_a_envelope(raw, b"", ps, baselines)
    good = apply_manifest(build_manifest(ps, baselines))
    outputs = validate_stage_a_envelope(
        json.dumps(good, sort_keys=True, separators=(",", ":")).encode(), b"", ps, baselines
    )
    target = atomic_stage(tmp_path, "phase5-abcdef", outputs)
    assert sorted(p.name for p in target.iterdir()) == [
        "calculator.py",
        "filters.py",
        "formatting.py",
    ]


def test_stage_b_host_requires_exit_zero_exact_trailer_and_empty_stderr():
    from phase5_sandbox import SUCCESS_TRAILER, classify_stage_b

    passed = classify_stage_b(0, SUCCESS_TRAILER, b"")
    assert passed.eligible is True and passed.classification == "PASS"
    cases = [
        (0, b"", b"", "FALSE_PASS"),
        (0, SUCCESS_TRAILER + b"extra", b"", "FALSE_PASS"),
        (0, SUCCESS_TRAILER, b"bad", "EVALUATOR_STDERR"),
        (1, b"", b"", "EVALUATOR_EXIT"),
    ]
    for exit_code, stdout, stderr, expected in cases:
        result = classify_stage_b(exit_code, stdout, stderr)
        assert result.eligible is False and result.classification == expected
    assert classify_stage_b(None, b"", b"", timed_out=True).classification == "TIMEOUT"
    assert (
        classify_stage_b(None, b"x" * 4097, b"", overflow=True).classification == "OUTPUT_OVERFLOW"
    )


def test_immutable_evaluator_rejects_partial_duplicate_extra_stderr_exit_and_overflow():
    from phase5_evaluator import ProtocolFailure, validate_worker_transcript

    cases = [{"id": "a", "expected": 1}, {"id": "b", "expected": 2}]
    good = [json.dumps({"id": "a", "value": 1}), json.dumps({"id": "b", "value": 2})]
    assert validate_worker_transcript(good, cases, b"", b"", 0) == 2
    bad_lines = [good[:1], [good[0], good[0]], good + [json.dumps({"id": "c", "value": 3})]]
    for lines in bad_lines:
        with pytest.raises(ProtocolFailure):
            validate_worker_transcript(lines, cases, b"", b"", 0)
    for kwargs in (
        {"worker_stdout": b"x"},
        {"worker_stderr": b"x"},
        {"exit_code": 1},
        {"overflow": True},
    ):
        values = {"worker_stdout": b"", "worker_stderr": b"", "exit_code": 0, "overflow": False}
        values.update(kwargs)
        with pytest.raises(ProtocolFailure):
            validate_worker_transcript(good, cases, **values)


def test_phase5_exact_changed_paths_and_candidate_identity_tamper_rejection(tmp_path):
    from phase5_sandbox import Phase5SandboxViolation, verify_candidate_identity

    ps = patchset()
    baselines = dict(SOURCES)
    outputs = ps.apply(baselines)
    identity = verify_candidate_identity(ps, baselines, outputs, expected_tree_hash=None)
    assert identity["changed_paths"] == list(ps.paths)
    tampered = dict(outputs)
    tampered["formatting.py"] += "# shadow\n"
    with pytest.raises(Phase5SandboxViolation):
        verify_candidate_identity(ps, baselines, tampered, expected_tree_hash=None)
    reordered = {p: outputs[p] for p in reversed(outputs)}
    with pytest.raises(Phase5SandboxViolation):
        verify_candidate_identity(ps, baselines, reordered, expected_tree_hash=None)


def test_phase5_inert_orphan_reporting_never_mutates_artifacts(tmp_path):
    from phase5_sandbox import find_inert_orphans

    root = tmp_path / "artifacts"
    root.mkdir()
    orphan = root / ".phase5-abcdef.staging-123"
    orphan.mkdir()
    (orphan / "x").write_text("evidence")
    retained = root / "phase5-fedcba"
    retained.mkdir()
    before = (orphan / "x").read_bytes()
    assert find_inert_orphans(root, {"phase5-fedcba"}) == [orphan]
    assert (orphan / "x").read_bytes() == before and retained.exists()


def test_phase5_docker_adapter_uses_two_separate_locked_commands(tmp_path):
    from phase5_sandbox import Phase5DockerSandbox

    fake = tmp_path / "docker.exe"
    fake.write_bytes(b"")
    adapter = Phase5DockerSandbox(tmp_path / "runtime", docker_executable=str(fake))
    a = adapter._container_argv("stage-a", [(tmp_path, "/input")])
    b = adapter._container_argv("stage-b", [(tmp_path, "/candidate")])
    for argv in (a, b):
        joined = " ".join(str(x) for x in argv)
        for flag in (
            "--pull=never",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--memory=64m",
            "--cpus=0.5",
            "--pids-limit=64",
            "--user=65534:65534",
        ):
            assert flag in joined
    assert a[-2:] == ["python", "/runner/phase5_stage_a.py"]
    assert b[-2:] == ["python", "/evaluator/phase5_evaluator.py"]
    assert a != b


def test_phase5_orphan_reporting_scans_real_candidate_and_artifact_roots(tmp_path):
    from phase5_sandbox import find_inert_orphans

    candidate_root = tmp_path / "phase5-sandbox" / "candidates"
    artifact_root = tmp_path / "phase5-artifacts"
    candidate_root.mkdir(parents=True)
    artifact_root.mkdir()
    residues = [
        candidate_root / ".phase5-a1b2c3.staging-111",
        candidate_root / "phase5-b1c2d3",
        artifact_root / ".phase5-c1d2e3.staging-222",
        artifact_root / "phase5-d1e2f3",
    ]
    for residue in residues:
        residue.mkdir()
        (residue / "evidence").write_text(residue.name, encoding="utf-8")
    for root in (candidate_root, artifact_root):
        committed = root / "phase5-eeeeee"
        committed.mkdir()
        (committed / "evidence").write_text("committed", encoding="utf-8")
    before = {path: (path / "evidence").read_bytes() for path in residues}

    found = find_inert_orphans((candidate_root, artifact_root), {"phase5-eeeeee"})

    assert found == sorted(residues, key=lambda p: str(p).encode("utf-8"))
    assert {(path / "evidence").read_bytes() for path in residues} == set(before.values())
    assert all(path.exists() for path in residues)