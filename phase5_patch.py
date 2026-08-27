from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

ALLOWLIST = ("calculator.py", "filters.py", "formatting.py")
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@$")
_PROHIBITED = (
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


class PatchSetValidationError(ValueError):
    """Variation Proposal payload or unified patch violates the closed contract."""


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PatchSetValidationError("duplicate JSON key")
        result[key] = value
    return result


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")


@dataclass(frozen=True)
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    body: tuple[str, ...]


@dataclass(frozen=True)
class ValidatedPatchMember:
    path: str
    raw: str
    hunks: tuple[Hunk, ...]

    @property
    def identity(self) -> str:
        return hashlib.sha256(self.raw.encode("utf-8")).hexdigest()

    @classmethod
    def parse(cls, path: str, raw: str) -> "ValidatedPatchMember":
        if path not in ALLOWLIST or not path.isascii():
            raise PatchSetValidationError("path is not allowlisted")
        if not isinstance(raw, str):
            raise PatchSetValidationError("patch must be a string")
        encoded = raw.encode("utf-8")
        if not raw or len(encoded) > 8192 or not raw.endswith("\n"):
            raise PatchSetValidationError("patch must be 1..8192 UTF-8 bytes and LF terminated")
        if raw.startswith("\ufeff") or any(c in raw for c in ("\r", "\x00", "\u2028", "\u2029")):
            raise PatchSetValidationError("patch contains prohibited text encoding")
        lines = raw[:-1].split("\n")
        if len(lines) < 4 or lines[0] != f"--- a/{path}" or lines[1] != f"+++ b/{path}":
            raise PatchSetValidationError("patch headers must be exact")
        if any(len(line.encode("utf-8")) > 500 for line in lines):
            raise PatchSetValidationError("patch line exceeds 500 UTF-8 bytes")
        if any(line.startswith(_PROHIBITED) for line in lines):
            raise PatchSetValidationError("prohibited patch operation")
        indices = [i for i, line in enumerate(lines) if line.startswith("@@")]
        if not 1 <= len(indices) <= 2 or indices[0] != 2:
            raise PatchSetValidationError("patch must contain one or two hunks")
        hunks: list[Hunk] = []
        for number, start in enumerate(indices):
            end = indices[number + 1] if number + 1 < len(indices) else len(lines)
            match = _HUNK.fullmatch(lines[start])
            if match is None:
                raise PatchSetValidationError("hunk header must be canonical without section text")
            values = [
                int(match.group(1)),
                int(match.group(2) or "1"),
                int(match.group(3)),
                int(match.group(4) or "1"),
            ]
            if min(values) < 1:
                raise PatchSetValidationError("hunks may only modify existing lines")
            body = tuple(lines[start + 1 : end])
            if not body or any(not line or line[0] not in " +-" for line in body):
                raise PatchSetValidationError("invalid hunk body")
            if any(line.startswith(("--- ", "+++ ")) for line in body):
                raise PatchSetValidationError("patch must contain exactly one file header pair")
            if not any(line.startswith(" ") for line in body):
                raise PatchSetValidationError("each hunk requires unchanged context")
            if not any(line.startswith(("+", "-")) for line in body):
                raise PatchSetValidationError("each member must change content")
            hunks.append(Hunk(*values, body))
        return cls(path, raw, tuple(hunks))

    def apply(self, source: str) -> str:
        if (
            not isinstance(source, str)
            or source.startswith("\ufeff")
            or "\r" in source
            or not source.endswith("\n")
        ):
            raise PatchSetValidationError("baseline must be canonical LF UTF-8 text")
        lines = source[:-1].split("\n")
        output: list[str] = []
        cursor = 0
        previous_end = 0
        for hunk in self.hunks:
            start = hunk.old_start - 1
            if start < cursor or start < previous_end or start > len(lines):
                raise PatchSetValidationError("hunks overlap, are out of order, or use an offset")
            output.extend(lines[cursor:start])
            cursor = start
            old_seen = new_seen = 0
            for row in hunk.body:
                prefix, text = row[0], row[1:]
                if prefix in " -":
                    if cursor >= len(lines) or lines[cursor] != text:
                        raise PatchSetValidationError("context/removal mismatch at exact position")
                    cursor += 1
                    old_seen += 1
                if prefix in " +":
                    output.append(text)
                    new_seen += 1
            if (old_seen, new_seen) != (hunk.old_count, hunk.new_count):
                raise PatchSetValidationError("hunk line counts mismatch")
            actual_new_start = len(output) - new_seen + 1
            if actual_new_start != hunk.new_start:
                raise PatchSetValidationError("new hunk position mismatch")
            previous_end = cursor
        output.extend(lines[cursor:])
        result = "\n".join(output) + "\n"
        if len(result.encode("utf-8")) > 16384:
            raise PatchSetValidationError("output source exceeds 16 KiB")
        if result == source:
            raise PatchSetValidationError("no-op patch member")
        return result


@dataclass(frozen=True)
class ValidatedPatchSet:
    members: tuple[ValidatedPatchMember, ...]
    rationale: str
    identity: str

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(member.path for member in self.members)

    @property
    def member_hashes(self) -> tuple[str, ...]:
        return tuple(member.identity for member in self.members)

    @property
    def rationale_hash(self) -> str:
        return hashlib.sha256(self.rationale.encode("utf-8")).hexdigest()

    @classmethod
    def parse(cls, raw: str) -> "ValidatedPatchSet":
        if (
            not isinstance(raw, str)
            or not raw
            or any(c in raw for c in ("\r", "\x00", "\u2028", "\u2029"))
        ):
            raise PatchSetValidationError("payload must be strict Unicode JSON")
        try:
            payload = json.loads(
                raw,
                object_pairs_hook=_pairs,
                parse_constant=lambda _: (_ for _ in ()).throw(
                    PatchSetValidationError("non-finite JSON")
                ),
            )
        except (json.JSONDecodeError, UnicodeError, TypeError) as exc:
            raise PatchSetValidationError("payload is not strict JSON") from exc
        if not isinstance(payload, dict) or set(payload) != {"patches", "rationale"}:
            raise PatchSetValidationError("top-level keys must be exactly patches and rationale")
        patches, rationale = payload["patches"], payload["rationale"]
        if not isinstance(patches, list) or not 2 <= len(patches) <= 3:
            raise PatchSetValidationError("patches must contain two or three members")
        if (
            not isinstance(rationale, str)
            or not rationale.strip()
            or len(rationale) > 1000
            or len(rationale.encode("utf-8")) > 4000
        ):
            raise PatchSetValidationError("rationale violates scalar or byte ceiling")
        members: list[ValidatedPatchMember] = []
        for item in patches:
            if (
                not isinstance(item, dict)
                or set(item) != {"path", "patch"}
                or not all(isinstance(item[k], str) for k in item)
            ):
                raise PatchSetValidationError("patch member schema is invalid")
            members.append(ValidatedPatchMember.parse(item["path"], item["patch"]))
        paths = [m.path for m in members]
        if paths != sorted(paths, key=lambda p: p.encode("utf-8")) or len(paths) != len(set(paths)):
            raise PatchSetValidationError("paths must be unique and canonical")
        if len({m.raw.encode("utf-8") for m in members}) != len(members):
            raise PatchSetValidationError("duplicate patch bytes")
        if sum(len(m.raw.encode("utf-8")) for m in members) > 16384:
            raise PatchSetValidationError("aggregate patch bytes exceed 16 KiB")
        canonical = {
            "patches": [{"path": m.path, "patch": m.raw} for m in members],
            "rationale": rationale,
        }
        identity = hashlib.sha256(_canonical(canonical)).hexdigest()
        return cls(tuple(members), rationale, identity)

    def apply(self, baselines: dict[str, str]) -> dict[str, str]:
        if set(self.paths) - set(baselines):
            raise PatchSetValidationError("missing baseline member")
        outputs = dict(baselines)
        for member in self.members:
            outputs[member.path] = member.apply(baselines[member.path])
        return outputs
