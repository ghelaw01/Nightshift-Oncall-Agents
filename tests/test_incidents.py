"""Every planted incident is real: the hidden test fails on the bug and passes on the true fix."""
import pytest

from nightshift import INCIDENTS, Workspace
from nightshift.agents import Resolution
from nightshift.evaluate import grade

BUGS = [i for i in INCIDENTS if i.kind == "bug"]


@pytest.mark.parametrize("inc", BUGS, ids=lambda i: i.id)
def test_planted_bug_is_caught_only_by_hidden_test(inc):
    ws = Workspace(inc)
    try:
        assert ws.team_tests_pass(), "the team's own tests must miss the bug, like in real life"
        assert not ws.hidden_test_passes()
        assert inc.commit_message in ws.recent_commits()
        (ws.repo / inc.file).write_text((ws.repo / inc.file).read_text().replace(inc.new, inc.old, 1))
        assert ws.hidden_test_passes()
    finally:
        ws.close()


def test_grader_rewards_a_real_fix_with_a_real_regression_test():
    inc = BUGS[0]
    ws = Workspace(inc)
    try:
        assert ws.edit_file(inc.file, inc.new, inc.old).startswith("edited")
        ws.create_test("test_regression_discount.py",
                       "from orders.pricing import apply_discount\n"
                       "def test_ten_percent():\n    assert apply_discount(10000, 10) == 9000\n")
        res = Resolution(inc.id, triage={"category": "code_bug", "severity": "high"},
                         diagnosis={"file": "./orders/pricing.py"}, approved=True)
        g = grade(ws, res)
        assert g["resolved"] and g["root_cause_file_ok"] and g["regression_test_catches_bug"]
    finally:
        ws.close()


def test_noise_is_resolved_only_by_changing_nothing():
    ws = Workspace(next(i for i in INCIDENTS if i.kind == "noise"))
    try:
        assert grade(ws, Resolution(ws.incident.id, triage={"category": "noise"}))["resolved"]
        assert not grade(ws, Resolution(ws.incident.id, triage={"category": "code_bug"}))["resolved"]
    finally:
        ws.close()
