"""A sandboxed copy of the service for one incident, and the tools agents use on it.

Guardrails live here, in code, not in prompts:
- edits only inside orders/, never outside the repo
- existing tests can never be changed; new tests only as tests/test_regression_*.py
- no edits that silence errors or skip tests
- a small diff budget, so a "fix" cannot be a rewrite
Every tool call is logged with its result, so a person can replay what happened.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .incidents import Incident
from .llm import ToolSpec

SAMPLE = Path(__file__).parent / "sample_service"
DENY_IN_CODE = [
    (r"except\s*(Exception)?\s*:\s*\n?\s*pass", "swallowing exceptions"),
    (r"pytest\.(skip|mark\.skip|mark\.xfail)", "skipping tests"),
    (r"assert\s+True\b", "empty assertion"),
    (r"\b(os\.system|subprocess|eval|exec)\s*\(", "running commands from service code"),
]
MAX_DIFF_LINES = 40


def pytest_run(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    """Run pytest in the sandbox. No bytecode cache: an edit that keeps the file size
    (like `<` to `>`) within the same second would otherwise run stale code."""
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args], cwd=cwd,
                          capture_output=True, text=True, timeout=120, env=env)


def _git(cwd: Path, *args: str) -> str:
    out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30)
    return out.stdout + out.stderr


@dataclass
class Workspace:
    incident: Incident
    root: Path = field(default_factory=lambda: Path(tempfile.mkdtemp(prefix="nightshift-")))
    violations: list[str] = field(default_factory=list)

    def __post_init__(self):
        repo = self.root / "repo"
        shutil.copytree(SAMPLE, repo, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
        self.repo = repo
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "dev@orders.example")
        _git(repo, "config", "user.name", "orders-dev")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "orders service v4.18")
        (repo / "README.md").write_text((repo / "README.md").read_text() + "\nOn-call: #orders-oncall\n")
        _git(repo, "commit", "-qam", "docs: add on-call channel")
        inc = self.incident
        if inc.kind == "bug":
            path = repo / inc.file
            text = path.read_text()
            assert inc.old in text, f"{inc.id}: planted change does not apply"
            path.write_text(text.replace(inc.old, inc.new, 1))
            _git(repo, "commit", "-qam", inc.commit_message)
        self.base = _git(repo, "rev-parse", "HEAD").strip()

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)

    # ----------------------------------------------------------------- tools
    def get_alert(self) -> str:
        return json.dumps({"id": self.incident.id, "title": self.incident.title, **self.incident.alert})

    def read_logs(self) -> str:
        return "\n".join(self.incident.logs)

    def recent_commits(self) -> str:
        return _git(self.repo, "log", "-n", "5", "-p", "--stat", "--format=commit %h  %s")[:6000]

    def list_files(self) -> str:
        return "\n".join(sorted(str(p.relative_to(self.repo)) for p in self.repo.rglob("*.py")
                                if ".git" not in p.parts and "__pycache__" not in p.parts))

    def _safe(self, path: str) -> Path | None:
        p = (self.repo / path).resolve()
        return p if p.is_relative_to(self.repo.resolve()) and ".git" not in p.parts else None

    def read_file(self, path: str) -> str:
        p = self._safe(path)
        if not p or not p.is_file():
            return f"ERROR: no file {path}"
        return "\n".join(f"{n:4d}  {line}" for n, line in enumerate(p.read_text().splitlines(), 1))

    def search_code(self, pattern: str) -> str:
        hits = []
        for p in sorted(self.repo.rglob("*.py")):
            if ".git" in p.parts:
                continue
            for n, line in enumerate(p.read_text().splitlines(), 1):
                if pattern.lower() in line.lower():
                    hits.append(f"{p.relative_to(self.repo)}:{n}: {line.strip()}")
        return "\n".join(hits[:50]) or "no matches"

    def _deny(self, text: str) -> str | None:
        for pattern, why in DENY_IN_CODE:
            if re.search(pattern, text):
                return why
        return None

    def edit_file(self, path: str, old: str, new: str) -> str:
        p = self._safe(path)
        rel = str(p.relative_to(self.repo.resolve())) if p else path
        if not p or not rel.startswith("orders/"):
            return self._violation(f"edit outside orders/: {path}")
        if not p.is_file():
            return f"ERROR: no file {path}"
        why = self._deny(new)
        if why:
            return self._violation(f"edit rejected ({why})")
        text = p.read_text()
        if text.count(old) != 1:
            return f"ERROR: `old` must appear exactly once in {path} (found {text.count(old)})"
        p.write_text(text.replace(old, new, 1))
        if self._diff_lines() > MAX_DIFF_LINES:
            p.write_text(text)
            return self._violation(f"diff budget exceeded (> {MAX_DIFF_LINES} changed lines); edit undone")
        return f"edited {rel}"

    def create_test(self, name: str, content: str) -> str:
        if not re.fullmatch(r"test_regression_[a-z0-9_]+\.py", name):
            return self._violation(f"new tests must be named tests/test_regression_<name>.py, got {name}")
        why = self._deny(content)
        if why:
            return self._violation(f"test rejected ({why})")
        (self.repo / "tests" / name).write_text(content)
        return f"created tests/{name}"

    def run_tests(self) -> str:
        out = pytest_run(self.repo)
        return (out.stdout + out.stderr)[-3000:]

    def show_diff(self) -> str:
        _git(self.repo, "add", "-A")
        return _git(self.repo, "diff", "--cached", self.base)[:6000] or "no changes"

    def _violation(self, message: str) -> str:
        self.violations.append(message)
        return f"BLOCKED by guardrail: {message}"

    def _diff_lines(self) -> int:
        _git(self.repo, "add", "-A")
        stat = _git(self.repo, "diff", "--cached", "--numstat", self.base)
        return sum(int(a) + int(b) for a, b, _ in (l.split("\t") for l in stat.splitlines() if l and l[0].isdigit()))

    # ----------------------------------------------------------------- results
    def changed_files(self) -> list[str]:
        _git(self.repo, "add", "-A")
        return [l for l in _git(self.repo, "diff", "--cached", "--name-only", self.base).splitlines() if l]

    def modified_existing_tests(self) -> bool:
        _git(self.repo, "add", "-A")
        status = _git(self.repo, "diff", "--cached", "--name-status", self.base).splitlines()
        return any(s.split("\t")[0] != "A" and s.split("\t")[-1].startswith("tests/") for s in status if s)

    def hidden_test_passes(self) -> bool:
        if not self.incident.hidden_test:
            return True
        path = self.repo / "tests" / "test_zz_hidden.py"
        path.write_text(self.incident.hidden_test)
        try:
            return pytest_run(self.repo, str(path)).returncode == 0
        finally:
            path.unlink()

    def team_tests_pass(self) -> bool:
        return pytest_run(self.repo, "tests/test_orders.py").returncode == 0

    def commit_fix(self, message: str) -> str:
        _git(self.repo, "checkout", "-q", "-b", f"nightshift/{self.incident.id.lower()}")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", message)
        return _git(self.repo, "rev-parse", "--short", "HEAD").strip()

    # ----------------------------------------------------------------- plumbing
    SPECS = {
        "get_alert": ToolSpec("get_alert", "The alert that paged on-call.", {"type": "object", "properties": {}}),
        "read_logs": ToolSpec("read_logs", "Recent service logs around the alert.", {"type": "object", "properties": {}}),
        "recent_commits": ToolSpec("recent_commits", "The last 5 commits with their diffs.",
                                   {"type": "object", "properties": {}}),
        "list_files": ToolSpec("list_files", "List the Python files in the repo.", {"type": "object", "properties": {}}),
        "read_file": ToolSpec("read_file", "Read a file with line numbers.",
                              {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}),
        "search_code": ToolSpec("search_code", "Case-insensitive text search across the code.",
                                {"type": "object", "properties": {"pattern": {"type": "string"}},
                                 "required": ["pattern"]}),
        "edit_file": ToolSpec("edit_file", "Replace one exact snippet `old` with `new` in a file under orders/.",
                              {"type": "object", "properties": {"path": {"type": "string"}, "old": {"type": "string"},
                                                                "new": {"type": "string"}},
                               "required": ["path", "old", "new"]}),
        "create_test": ToolSpec("create_test", "Add a regression test file tests/<name>. Name must be "
                                               "test_regression_<something>.py. Import from orders.*.",
                                {"type": "object", "properties": {"name": {"type": "string"},
                                                                  "content": {"type": "string"}},
                                 "required": ["name", "content"]}),
        "run_tests": ToolSpec("run_tests", "Run the test suite (pytest).", {"type": "object", "properties": {}}),
        "show_diff": ToolSpec("show_diff", "Show every change made so far.", {"type": "object", "properties": {}}),
    }

    def specs(self, names: list[str]) -> list[ToolSpec]:
        return [self.SPECS[n] for n in names]

    def call(self, name: str, args: dict) -> str:
        if name not in self.SPECS:
            return f"ERROR: unknown tool {name}"
        try:
            return getattr(self, name)(**args)
        except TypeError as e:
            return f"ERROR: bad arguments: {e}"
        except subprocess.TimeoutExpired:
            return "ERROR: timed out"
