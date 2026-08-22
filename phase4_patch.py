from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@$")
_PROHIBITED_PREFIXES = (
    "diff --git ",
    "new file mode ",
    "deleted file mode ",
    "old mode ",
    "new mode ",
    "rename from ",
    "rename to ",
    "copy from ",
    "copy to ",
    "GIT binary patch",
    "Binary files ",
    "Subproject commit ",
    "\\ No newline at end of file",
)


class PatchValidationError(ValueError):
    """Raised when a Phase 4 unified patch exceeds the closed contract."""


@dataclass(frozen=True)
class ValidatedPatch:
    raw: str
    target_path: str
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    body: tuple[str, ...]

    @classmethod
    def parse(cls, payload: str) -> "ValidatedPatch":
        if not isinstance(payload, str):
            raise PatchValidationError("patch must be UTF-8 text")
        encoded = payload.encode("utf-8")
        if len(encoded) > 8192:
            raise PatchValidationError("patch must be at most 8192 bytes")
        if not payload or "\x00" in payload or "\r" in payload or not payload.endswith("\n"):
            raise PatchValidationError("patch must be NUL-free LF text ending with newline")
        lines = payload.splitlines()
        if len(lines) < 4:
            raise PatchValidationError("patch is incomplete")
        if lines[0] != "--- a/calculator.py" or lines[1] != "+++ b/calculator.py":
            raise PatchValidationError("patch must update only calculator.py")
        if any(line.startswith(_PROHIBITED_PREFIXES) for line in lines):
            raise PatchValidationError("patch contains a prohibited Git operation")
        if any(len(line) > 500 for line in lines):
            raise PatchValidationError("patch lines must be at most 500 characters")
        hunk_indices = [index for index, line in enumerate(lines) if line.startswith("@@")]
        if hunk_indices != [2]:
            raise PatchValidationError("patch must contain exactly one hunk")
        match = _HUNK.fullmatch(lines[2])
        if match is None:
            raise PatchValidationError("hunk header is invalid")
        old_start = int(match.group(1))
        old_count = int(match.group(2) or "1")
        new_start = int(match.group(3))
        new_count = int(match.group(4) or "1")
        if min(old_start, old_count, new_start, new_count) < 1:
            raise PatchValidationError("patch must modify existing lines")
        body = tuple(lines[3:])
        if not body or any(not line or line[0] not in {" ", "+", "-"} for line in body):
            raise PatchValidationError("hunk body contains an invalid line")
        if any(line.startswith(("--- ", "+++ ")) for line in body):
            raise PatchValidationError("patch must contain exactly one file")
        return cls(
            payload,
            "calculator.py",
            old_start,
            old_count,
            new_start,
            new_count,
            body,
        )

    @property
    def identity(self) -> str:
        return hashlib.sha256(self.raw.encode("utf-8")).hexdigest()

    def apply(self, source: str) -> str:
        if not isinstance(source, str) or "\r" in source or not source.endswith("\n"):
            raise PatchValidationError("baseline source must be canonical LF text")
        source_lines = source.splitlines()
        source_index = self.old_start - 1
        if source_index > len(source_lines):
            raise PatchValidationError("hunk starts outside the baseline")
        output = list(source_lines[:source_index])
        old_seen = 0
        new_seen = 0
        for line in self.body:
            prefix, content = line[0], line[1:]
            if prefix in {" ", "-"}:
                if source_index >= len(source_lines) or source_lines[source_index] != content:
                    raise PatchValidationError("patch context does not match the baseline")
                source_index += 1
                old_seen += 1
            if prefix in {" ", "+"}:
                output.append(content)
                new_seen += 1
        if old_seen != self.old_count or new_seen != self.new_count:
            raise PatchValidationError("hunk line counts do not match its header")
        expected_new_start = len(output) - new_seen + 1
        if expected_new_start != self.new_start:
            raise PatchValidationError("new hunk start does not match the output")
        output.extend(source_lines[source_index:])
        return "\n".join(output) + "\n"
