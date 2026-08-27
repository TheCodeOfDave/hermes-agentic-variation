from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

SOURCE_PATHS = ("calculator.py", "filters.py", "formatting.py")
SOURCES = {
    "calculator.py": "anchor = 0\nvalue = 1\n\ndef total(values):\n    return sum(values) + 1\n",
    "filters.py": "anchor = 0\nvalue = 1\n\ndef select(values):\n    return [item for item in values if item % 2 == 1]\n",
    "formatting.py": "anchor = 0\nvalue = 1\n\ndef format_result(value):\n    return f'total={value}'\n",
}
CASES = (
    {"id": "even-basic", "values": [1, 2, 4], "expected": "total=6"},
    {"id": "even-negative", "values": [-2, -1, 3, 8], "expected": "total=6"},
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class FixtureFacts:
    repository_path: Path
    source_paths: tuple[str, ...]
    source_hashes: dict[str, str]
    cases_path: Path
    cases_hash: str


class Phase5Fixture:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def create(self, run_id: str) -> FixtureFacts:
        if not isinstance(run_id, str) or not run_id.startswith("phase5-"):
            raise ValueError("run_id is not a Variation Cycle identifier")
        repo = self.root / run_id
        repo.mkdir(parents=True, exist_ok=False)
        for path in SOURCE_PATHS:
            (repo / path).write_text(SOURCES[path], encoding="utf-8", newline="\n")
        cases = repo.parent / f"{run_id}-immutable"
        cases.mkdir()
        cases_path = cases / "phase5_cases.json"
        case_bytes = json.dumps(CASES, sort_keys=True, separators=(",", ":")).encode("utf-8")
        cases_path.write_bytes(case_bytes)
        subprocess.run(
            ["git", "init", "--quiet", str(repo)],
            check=True,
            capture_output=True,
            stdin=subprocess.DEVNULL,
        )
        return FixtureFacts(
            repo,
            SOURCE_PATHS,
            {p: sha((repo / p).read_bytes()) for p in SOURCE_PATHS},
            cases_path,
            sha(case_bytes),
        )

    @staticmethod
    def git_facts(repository_path: str | Path) -> dict[str, object]:
        repo = Path(repository_path)
        count = subprocess.run(
            ["git", "rev-list", "--all", "--count"],
            cwd=repo,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        remotes = subprocess.run(
            ["git", "remote"], cwd=repo, text=True, capture_output=True, check=True
        ).stdout.splitlines()
        return {"commit_count": int(count or "0"), "remotes": remotes}
