from __future__ import annotations

import json
import pytest

from phase5_patch import PatchSetValidationError, ValidatedPatchSet


def member(path: str, old: str = "value = 1", new: str = "value = 2") -> dict[str, str]:
    return {
        "path": path,
        "patch": f"--- a/{path}\n+++ b/{path}\n@@ -1,2 +1,2 @@\n anchor = 0\n-{old}\n+{new}\n",
    }


def payload(paths=("calculator.py", "filters.py"), rationale="bounded reason") -> str:
    return json.dumps({"patches": [member(path) for path in paths], "rationale": rationale})


def test_phase5_patchset_contract_and_canonical_identity():
    first = ValidatedPatchSet.parse(payload())
    second = ValidatedPatchSet.parse(payload())
    assert first.identity == second.identity
    assert first.paths == ("calculator.py", "filters.py")
    assert len(first.member_hashes) == 2


@pytest.mark.parametrize(
    "raw",
    [
        payload(("calculator.py",)),
        payload(("calculator.py", "filters.py", "formatting.py", "other.py")),
        payload(("filters.py", "calculator.py")),
        payload(("calculator.py", "calculator.py")),
        payload(("calculator.py", "unknown.py")),
    ],
)
def test_phase5_patchset_cardinality_order_and_allowlist_rejections(raw):
    with pytest.raises(PatchSetValidationError):
        ValidatedPatchSet.parse(raw)


def test_phase5_patchset_numeric_and_text_boundaries():
    with pytest.raises(PatchSetValidationError):
        ValidatedPatchSet.parse(payload(rationale="x" * 1001))
    with pytest.raises(PatchSetValidationError):
        ValidatedPatchSet.parse(payload(rationale="Ã°Å¸Ëœâ‚¬" * 1001))
    with pytest.raises(PatchSetValidationError):
        ValidatedPatchSet.parse(payload().replace("value = 2", "x" * 501))
    for bad in ("\r", "\x00", "\u2028", "\u2029"):
        with pytest.raises(PatchSetValidationError):
            ValidatedPatchSet.parse(payload().replace("bounded reason", "bad" + bad))


def test_phase5_plugin_owned_fixture_has_exact_three_sources_and_no_history(tmp_path):
    from phase5_fixture import Phase5Fixture

    fixture = Phase5Fixture(tmp_path / "runs")
    facts = fixture.create("phase5-abcdef")
    assert facts.source_paths == ("calculator.py", "filters.py", "formatting.py")
    assert set(facts.source_hashes) == set(facts.source_paths)
    assert fixture.git_facts(facts.repository_path) == {"commit_count": 0, "remotes": []}


def test_phase5_two_and_three_file_atomic_application(tmp_path):
    from phase5_fixture import Phase5Fixture

    fixture = Phase5Fixture(tmp_path / "runs").create("phase5-abcdef")
    baselines = {
        p: (fixture.repository_path / p).read_text(encoding="utf-8") for p in fixture.source_paths
    }
    two = ValidatedPatchSet.parse(
        json.dumps(
            {
                "patches": [
                    member("calculator.py"),
                    member("filters.py"),
                ],
                "rationale": "two",
            }
        )
    )
    outputs = two.apply(baselines)
    assert set(p for p in baselines if outputs[p] != baselines[p]) == set(two.paths)
    three_raw = json.loads(payload(("calculator.py", "filters.py", "formatting.py"), "three"))
    three = ValidatedPatchSet.parse(json.dumps(three_raw))
    assert len(three.paths) == 3


def test_phase5_hunk_parser_rejects_embedded_second_file_header():
    raw = json.dumps(
        {
            "patches": [
                {
                    "path": "calculator.py",
                    "patch": "--- a/calculator.py\n+++ b/calculator.py\n@@ -1,2 +1,2 @@\n anchor = 0\n--- a/filters.py\n+++ b/filters.py\n",
                },
                member("filters.py"),
            ],
            "rationale": "strict hunk",
        }
    )
    with pytest.raises(PatchSetValidationError):
        ValidatedPatchSet.parse(raw)


def test_phase5_hunk_application_rejects_offset_context_and_optional_section():
    baseline = "anchor = 0\nvalue = 1\n"
    valid = ValidatedPatchSet.parse(payload())
    with pytest.raises(PatchSetValidationError):
        valid.members[0].apply("prefix = 9\n" + baseline)
    bad = payload().replace("@@ -1,2 +1,2 @@", "@@ -1,2 +1,2 @@ section")
    with pytest.raises(PatchSetValidationError):
        ValidatedPatchSet.parse(bad)
