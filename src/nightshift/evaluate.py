"""Grade one response against the incident's ground truth."""
from __future__ import annotations

from .agents import Resolution
from .workspace import Workspace, _git, pytest_run


def _norm(path) -> str:
    return str(path or "").strip().lstrip("./").removeprefix("repo/")


def regression_test_catches_bug(ws: Workspace) -> bool:
    """The agent's new test must fail on the buggy code (same check as the ship gate)."""
    return ws.regression_tests_fail_on_original()


def grade(ws: Workspace, res: Resolution) -> dict:
    inc = ws.incident
    changed = ws.changed_files()
    code_changed = [f for f in changed if f.startswith("orders/")]
    category = str(res.triage.get("category") or "").lower()
    # Map free-form labels ("infrastructure_problem", "Noise") to the three categories.
    category = next((c for c in ("code_bug", "noise", "infra") if category.startswith(c.split("_")[0])), category)
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
