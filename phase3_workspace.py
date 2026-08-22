from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_BASELINE = """def sum_even(numbers):
    return sum(numbers)
"""
_FILTER_ODD = """def sum_even(numbers):
    return sum(number for number in numbers if number % 2 != 0)
"""
_FILTER_EVEN = """def sum_even(numbers):
    return sum(number for number in numbers if number % 2 == 0)
"""
_TEST = """import unittest

from calculator import sum_even


class CalculatorTests(unittest.TestCase):
    def test_sums_only_even_integers(self):
        self.assertEqual(sum_even([1, 2, 3, 4, 5, 6]), 12)

    def test_empty_input(self):
        self.assertEqual(sum_even([]), 0)


if __name__ == \"__main__\":
    unittest.main()
"""
_MUTATIONS = {
    "baseline": _BASELINE,
    "filter_odd": _FILTER_ODD,
    "filter_even": _FILTER_EVEN,
}
_ALLOWED_FILES = ("calculator.py", "test_calculator.py")


class WorkspaceViolation(ValueError):
    """Raised when a Phase 3 workspace request exceeds its fixed boundary."""


@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    exit_code: int
    tests_passed: bool
    stdout: bytes
    stderr: bytes

    @property
    def stdout_hash(self) -> str:
        return hashlib.sha256(self.stdout).hexdigest()

    @property
    def stderr_hash(self) -> str:
        return hashlib.sha256(self.stderr).hexdigest()


class Phase3Workspace:
    """Create and evaluate one trusted-template disposable repository."""

    def __init__(
        self,
        root: str | Path,
        *,
        test_timeout_seconds: int,
        repository_prefix: str = "phase3",
    ):
        raw_root = Path(root)
        if raw_root.exists() and raw_root.is_symlink():
            raise WorkspaceViolation("workspace root must not be a symlink")
        self.root = raw_root.resolve()
        if type(test_timeout_seconds) is not int or not 1 <= test_timeout_seconds <= 60:
            raise WorkspaceViolation("test timeout must be an integer from 1 to 60")
        self.test_timeout_seconds = test_timeout_seconds
        if repository_prefix not in {"phase3", "phase4"}:
            raise WorkspaceViolation("repository prefix is invalid")
        self.repository_prefix = repository_prefix
        git = shutil.which("git")
        if not git:
            raise WorkspaceViolation("git executable is required for Phase 3")
        self.git_executable = str(Path(git).resolve())

    def create(self, repository_id: str) -> Path:
        pattern = rf"{re.escape(self.repository_prefix)}-[0-9a-f]{{6,32}}"
        if not isinstance(repository_id, str) or re.fullmatch(pattern, repository_id) is None:
            raise WorkspaceViolation("repository_id is invalid")
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink():
            raise WorkspaceViolation("workspace root must not be a symlink")
        repo = self.root / repository_id
        repo.mkdir(parents=False, exist_ok=False)
        resolved = repo.resolve()
        if resolved.parent != self.root or resolved.is_symlink():
            raise WorkspaceViolation("repository escaped the Phase 3 root")
        self._write_trusted(resolved, "calculator.py", _BASELINE)
        self._write_trusted(resolved, "test_calculator.py", _TEST)
        self._run_git(resolved, ["init", "--quiet"])
        return resolved

    def apply(self, repo: str | Path, mutation: str) -> tuple[str, ...]:
        resolved = self._validate_repo(repo)
        if mutation not in _MUTATIONS:
            raise WorkspaceViolation("mutation is not a supported Phase 3 enum")
        if mutation == "baseline":
            return ()
        self._write_trusted(resolved, "calculator.py", _MUTATIONS[mutation])
        return ("calculator.py",)

    def evaluate(self, repo: str | Path) -> CommandResult:
        resolved = self._validate_repo(repo)
        env = {"PYTHONIOENCODING": "utf-8", "PYTHONNOUSERSITE": "1"}
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "unittest", "-q"],
                cwd=resolved,
                env=env,
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.test_timeout_seconds,
                check=False,
            )
            exit_code = int(completed.returncode)
            stdout = completed.stdout
            stderr = completed.stderr
        except subprocess.TimeoutExpired as exc:
            exit_code = 124
            stdout = exc.stdout or b""
            stderr = (exc.stderr or b"") + b"\nPHASE3_TEST_TIMEOUT"
        return CommandResult(
            argv=("python", "-m", "unittest", "-q"),
            exit_code=exit_code,
            tests_passed=exit_code == 0,
            stdout=stdout,
            stderr=stderr,
        )

    def tree_hash(self, repo: str | Path) -> str:
        resolved = self._validate_repo(repo)
        digest = hashlib.sha256()
        for relative in _ALLOWED_FILES:
            path = self._allowed_path(resolved, relative)
            payload = path.read_bytes()
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(hashlib.sha256(payload).digest())
        return digest.hexdigest()

    def git_facts(self, repo: str | Path) -> dict[str, object]:
        resolved = self._validate_repo(repo)
        commits = self._run_git(resolved, ["rev-list", "--count", "--all"])
        remotes = self._run_git(resolved, ["remote"])
        return {
            "commit_count": int((commits.stdout or b"0").strip() or b"0"),
            "remotes": [line for line in remotes.stdout.decode("utf-8").splitlines() if line],
        }

    def _validate_repo(self, repo: str | Path) -> Path:
        path = Path(repo)
        if path.is_symlink():
            raise WorkspaceViolation("repository must not be a symlink")
        resolved = path.resolve()
        if resolved.parent != self.root or not (resolved / ".git").is_dir():
            raise WorkspaceViolation("repository is outside the Phase 3 root")
        for relative in _ALLOWED_FILES:
            self._allowed_path(resolved, relative)
        return resolved

    def _allowed_path(self, repo: Path, relative: str) -> Path:
        path = repo / relative
        if path.is_symlink() or path.resolve().parent != repo:
            raise WorkspaceViolation("fixture file escaped the repository")
        return path

    def _write_trusted(self, repo: Path, relative: str, content: str) -> None:
        path = self._allowed_path(repo, relative)
        temporary = repo / f".{relative}.phase3-new"
        if temporary.exists() or temporary.is_symlink():
            raise WorkspaceViolation("temporary mutation path is not clean")
        temporary.write_text(content, encoding="utf-8", newline="\n")
        os.replace(temporary, path)

    def _run_git(self, repo: Path, arguments: list[str]) -> subprocess.CompletedProcess[bytes]:
        env = {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "HOME": str(repo),
            "PATH": str(Path(self.git_executable).parent),
        }
        for name in ("SYSTEMROOT", "WINDIR"):
            if os.environ.get(name):
                env[name] = os.environ[name]
        try:
            return subprocess.run(
                [self.git_executable, "-c", "init.templateDir=", *arguments],
                cwd=repo,
                env=env,
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=20,
                check=True,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise WorkspaceViolation("fixed git command failed") from exc
