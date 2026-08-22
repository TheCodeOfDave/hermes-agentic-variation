from __future__ import annotations

import pytest

from phase4_patch import PatchValidationError, ValidatedPatch

BASELINE = """def sum_even(numbers):
    return sum(numbers)
"""
VALID = """--- a/calculator.py
+++ b/calculator.py
@@ -1,2 +1,2 @@
 def sum_even(numbers):
-    return sum(numbers)
+    return sum(number for number in numbers if number % 2 == 0)
"""


def test_valid_patch_applies_exactly_one_existing_file():
    patch = ValidatedPatch.parse(VALID)

    result = patch.apply(BASELINE)

    assert patch.target_path == "calculator.py"
    assert len(patch.identity) == 64
    assert result == (
        "def sum_even(numbers):\n"
        "    return sum(number for number in numbers if number % 2 == 0)\n"
    )


@pytest.mark.parametrize(
    "payload",
    [
        "--- /dev/null\n+++ b/calculator.py\n@@ -0,0 +1 @@\n+bad\n",
        "--- a/calculator.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-bad\n",
        "--- a/../escape.py\n+++ b/../escape.py\n@@ -1 +1 @@\n-a\n+b\n",
        "--- a/other.py\n+++ b/other.py\n@@ -1 +1 @@\n-a\n+b\n",
        "diff --git a/calculator.py b/calculator.py\n" + VALID,
        "new file mode 100644\n" + VALID,
        "rename from calculator.py\nrename to other.py\n" + VALID,
        "GIT binary patch\n" + VALID,
        VALID + "--- a/second.py\n+++ b/second.py\n@@ -1 +1 @@\n-a\n+b\n",
        VALID.replace("@@ -1,2 +1,2 @@", "@@ -1,2 +1,2 @@\n@@ -1 +1 @@"),
        VALID.replace("-    return sum(numbers)", "-    return not_the_baseline"),
        VALID + "\\ No newline at end of file\n",
        VALID.replace("\n", "\r\n"),
        VALID + "\x00",
        "--- a/calculator.py\n+++ b/calculator.py\n@@ -1 +1 @@\n-" + "x" * 501 + "\n+y\n",
    ],
)
def test_patch_rejects_prohibited_or_nonmatching_forms(payload):
    with pytest.raises(PatchValidationError):
        patch = ValidatedPatch.parse(payload)
        patch.apply(BASELINE)


def test_patch_rejects_oversized_payload():
    payload = VALID + (" " * 8192)

    with pytest.raises(PatchValidationError, match="8192"):
        ValidatedPatch.parse(payload)
