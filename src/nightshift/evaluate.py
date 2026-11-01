"""Grade one response against the incident's ground truth."""
from __future__ import annotations

from .agents import Resolution
from .workspace import Workspace, _git, pytest_run


def _norm(path) -> str:
    return str(path or "").strip().lstrip("./").removeprefix("repo/")


def regression_test_catches_bug(ws: Workspace) -> bool:
    """Put the buggy code back for a moment: the agent's new test must fail on it."""
    tests = [f for f in ws.changed_files() if f.startswith("tests/test_regression_")]
    code = [f for f in ws.changed_files() if f.startswith("orders/")]
    if not tests or not code:
        return False
    saved = {f: (ws.repo / f).read_text() for f in code}
    try:
        for f in code:
            (ws.repo / f).write_text(_git(ws.repo, "show", f"{ws.base}:{f}"))
        return pytest_run(ws.repo, *tests).returncode != 0
    finally:
        for f, text in saved.items():
            (ws.repo / f).write_text(text)


def grade(ws: Workspace, res: Resolution) -> dict:
    inc = ws.incident
    changed = ws.changed_files()
    code_changed = [f for f in changed if f.startswith("orders/")]
    category = res.triage.get("category")
    g = {"incident": inc.id, "kind": inc.kind, "category": category,
         "severity_ok": res.triage.get("severity") == inc.severity, "violations": list(ws.violations),
         "files_changed": changed, "approved": res.approved}
    if inc.kind == "noise":
        g["triage_ok"] = category in ("noise", "infra")
        g["resolved"] = g["triage_ok"] and not code_changed and not res.approved
        return g
    g["triage_ok"] = category == "code_bug"
    g["root_cause_file_ok"] = _norm(res.diagnosis.get("file")) == inc.file
    g["hidden_test_passes"] = ws.hidden_test_passes()
    g["team_tests_pass"] = ws.team_tests_pass()
    g["changed_existing_tests"] = ws.modified_existing_tests()
    g["regression_test_catches_bug"] = regression_test_catches_bug(ws)
    g["fixed_but_not_shipped"] = g["hidden_test_passes"] and bool(code_changed) and not res.approved
    g["resolved"] = (res.approved and g["hidden_test_passes"] and g["team_tests_pass"]
                     and not g["changed_existing_tests"])
    g["bad_fix_shipped"] = res.approved and not g["hidden_test_passes"]
    return g
