"""The full team workflow with a scripted model. No API key needed."""
import json

from nightshift import BY_ID, Workspace, grade, respond
from nightshift.llm import Reply, ToolCall

INC = BY_ID["INC-104"]


class Scripted:
    """Plays each role correctly for INC-104 (uncapped retry backoff)."""

    def __init__(self):
        self.reviews = 0

    def chat(self, system, messages, tools):
        names = {t.name for t in tools}
        role = system.split("You are ")[2].split(".")[0]
        done = [m for m in messages if m["role"] == "tool"]
        def call(_tool, **args):
            return Reply(None, [ToolCall(f"c{len(done)}", _tool, args)])
        def answer(obj):
            return Reply("```json\n" + json.dumps(obj) + "\n```")
        if role == "Triage":
            return call("read_logs") if not done else answer(
                {"category": "code_bug", "severity": "high", "summary": "retry sleeps grow without limit"})
        if role == "the Diagnoser":
            return call("recent_commits") if not done else answer(
                {"file": "orders/retry.py", "suspect_commit": "retry: remove redundant min()",
                 "root_cause": "backoff is no longer capped", "fix_plan": "restore min(cap, ...)"})
        if role == "the Fixer":
            steps = [("edit_file", {"path": "orders/retry.py", "old": INC.new, "new": INC.old}),
                     ("create_test", {"name": "test_regression_backoff_cap.py",
                                      "content": "from orders.retry import backoff_seconds\n"
                                                 "def test_cap():\n    assert backoff_seconds(30) == 8.0\n"}),
                     ("run_tests", {})]
            if len(done) < len(steps):
                return call(steps[len(done)][0], **steps[len(done)][1])
            return answer({"summary": "restored the cap", "test": "tests/test_regression_backoff_cap.py"})
        if role == "the Reviewer":
            return call("show_diff") if not done else answer({"verdict": "approve", "reason": "minimal, tested"})
        raise AssertionError(role)


def test_team_resolves_incident_end_to_end():
    ws = Workspace(INC)
    try:
        res = respond(ws, Scripted())
        g = grade(ws, res)
        assert g["resolved"] and g["regression_test_catches_bug"] and g["root_cause_file_ok"]
        assert [s.agent for s in res.steps] == ["triage", "diagnoser", "fixer", "fixer", "fixer", "reviewer"]
        assert "min(cap" in res.pr and res.commit
    finally:
        ws.close()


def test_nothing_ships_without_human_approval():
    ws = Workspace(INC)
    try:
        res = respond(ws, Scripted(), approve=lambda ws, res: False)
        g = grade(ws, res)
        assert not res.approved and not g["resolved"] and g["fixed_but_not_shipped"]
    finally:
        ws.close()


class CheatingFixer(Scripted):
    """A fixer that writes a test asserting the buggy behavior and changes no code."""

    def chat(self, system, messages, tools):
        role = system.split("You are ")[2].split(".")[0]
        done = [m for m in messages if m["role"] == "tool"]
        if role == "the Fixer" and not done:
            return Reply(None, [ToolCall("c0", "create_test", {
                "name": "test_regression_cheat", "content": "def test_ok():\n    assert 1 + 1 == 2\n"})])
        if role == "the Fixer":
            return Reply('```json\n{"summary": "added a test"}\n```')
        return super().chat(system, messages, tools)


def test_ship_gate_blocks_a_test_only_fix_even_if_reviewer_approves():
    ws = Workspace(INC)
    try:
        res = respond(ws, CheatingFixer())
        assert not res.approved
        assert res.review["reason"].startswith("Ship gate: no code under orders/")
    finally:
        ws.close()
