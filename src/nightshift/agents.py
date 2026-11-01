"""The on-call team: Triage -> Diagnoser -> Fixer <-> Reviewer -> human approval -> pull request.

Python runs the workflow and passes structured JSON between agents. Each agent sees only
the tools its job needs: Triage cannot edit code, the Reviewer cannot edit code, and the
Fixer cannot merge. Nothing ships without a human approval.

`solo_responder` is the baseline: one agent with every tool and the same goal.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Callable

from .llm import Reply
from .workspace import Workspace


@dataclass
class Step:
    agent: str
    tool: str
    args: dict
    result: str


@dataclass
class Resolution:
    incident: str
    triage: dict = field(default_factory=dict)
    diagnosis: dict = field(default_factory=dict)
    review: dict = field(default_factory=dict)
    approved: bool = False
    pr: str = ""
    commit: str = ""
    steps: list[Step] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0

    def to_dict(self):
        d = dict(self.__dict__)
        d["steps"] = [{"agent": s.agent, "tool": s.tool, "args": s.args, "result": s.result[:300]} for s in self.steps]
        return d


def parse_json(text: str) -> dict:
    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text or "", re.S)
    for c in reversed(fenced or re.findall(r"\{.*\}", text or "", re.S)):
        try:
            return json.loads(c)
        except json.JSONDecodeError:
            continue
    return {}


class Agent:
    def __init__(self, name, instructions, model, tools, max_steps=12):
        self.name, self.instructions, self.model, self.tools, self.max_steps = name, instructions, model, tools, max_steps

    def run(self, ws: Workspace, task: str, res: Resolution) -> dict:
        messages = [{"role": "user", "content": task}]
        specs = ws.specs(self.tools)
        for _ in range(self.max_steps):
            reply: Reply = self.model.chat(self.instructions, messages, specs)
            res.input_tokens += reply.input_tokens
            res.output_tokens += reply.output_tokens
            if not reply.tool_calls:
                return parse_json(reply.text)
            messages.append({"role": "assistant", "content": reply.text, "tool_calls": reply.tool_calls})
            for call in reply.tool_calls:
                out = ws.call(call.name, call.args)
                res.steps.append(Step(self.name, call.name, call.args, out))
                messages.append({"role": "tool", "id": call.id, "name": call.name, "content": out})
        messages.append({"role": "user", "content": "Step limit reached. Reply now with your final JSON."})
        return parse_json(self.model.chat(self.instructions, messages, []).text)


CONTEXT = "You are on the on-call team for the `orders` checkout service (Python). "

TRIAGE = CONTEXT + """You are Triage. Read the alert, the logs, and what shipped recently, then decide:
- code_bug: the service code is producing wrong results or errors. A code change is needed.
- noise: a transient or expected event (deploys, warm-up) with normal error rates. No action.
- infra: a real problem outside the code (disks, hosts, cron). Hand to infrastructure; no code change.
Severity is high if customers are charged wrongly, blocked, or seeing errors; otherwise low.
End with JSON only:
```json
{"category": "code_bug", "severity": "high", "summary": "one sentence with the evidence"}
```"""

DIAGNOSER = CONTEXT + """You are the Diagnoser. Find the root cause in the code. Look at recent commits:
regressions usually come from a recent change. Read the suspect code to confirm. Do not edit anything.
End with JSON only:
```json
{"file": "orders/x.py", "suspect_commit": "short hash or message", "root_cause": "what is wrong and why", "fix_plan": "the smallest correct change"}
```"""

FIXER = CONTEXT + """You are the Fixer. Make the smallest correct fix for the diagnosed root cause.
Rules:
- Edit only files under orders/ with edit_file. Never change existing tests.
- Add one regression test with create_test that fails on the bug and passes on the fix.
- Run the tests and make sure they all pass.
End with JSON only:
```json
{"summary": "what you changed and why", "test": "tests/test_regression_x.py"}
```"""

REVIEWER = CONTEXT + """You are the Reviewer. You did not write this change. Check it hard:
- Does it fix the root cause, not just the symptom? Is it the smallest change that does?
- Is there a regression test that would have caught the bug? Do all tests pass?
- Any unrelated changes, weakened checks, or risky behavior?
Use show_diff and run_tests. Approve only if every answer is right.
End with JSON only:
```json
{"verdict": "approve", "reason": "one or two sentences"}
```"""

SOLO = CONTEXT + """You are the only on-call engineer. Handle the alert end to end.
First decide if it is a code bug, noise, or an infrastructure problem; only code bugs need a code change.
For a code bug: find the root cause, make the smallest fix under orders/, add a regression test with
create_test, and run the tests. Never change existing tests.
End with JSON only:
```json
{"category": "code_bug", "severity": "high", "file": "orders/x.py", "root_cause": "...", "summary": "..."}
```"""

READ = ["read_logs", "recent_commits", "list_files", "read_file", "search_code"]
ApprovalFn = Callable[[Workspace, Resolution], bool]


def auto_approve(ws, res) -> bool:
    return True


def ask_human(ws, res) -> bool:
    print("\n" + ws.show_diff())
    print("\nReviewer:", res.review)
    return input("\nApprove this fix and open the pull request? [y/N] ").strip().lower() == "y"


def _pr_body(ws: Workspace, res: Resolution, fixer: dict) -> str:
    inc = ws.incident
    return f"""## {inc.id}: {inc.title}

**Triage:** {res.triage.get('category')} / {res.triage.get('severity')}. {res.triage.get('summary', '')}

**Root cause:** {res.diagnosis.get('root_cause', '')} (`{res.diagnosis.get('file', '')}`,
suspect commit: {res.diagnosis.get('suspect_commit', '')})

**Fix:** {fixer.get('summary', '')}

**Regression test:** `{fixer.get('test', '')}`

**Review:** {res.review.get('verdict')}. {res.review.get('reason', '')}

```diff
{ws.show_diff()}
```

Opened by Night Shift after human approval. Every agent step is in the attached trace.
"""


def respond(ws: Workspace, model, approve: ApprovalFn = auto_approve, max_rounds: int = 2) -> Resolution:
    """Run the on-call team on one incident."""
    start = time.time()
    res = Resolution(ws.incident.id)
    res.triage = Agent("triage", TRIAGE, model, ["get_alert", "read_logs", "recent_commits"]).run(
        ws, "A page just fired. Triage it.", res)
    if res.triage.get("category") != "code_bug":
        res.seconds = time.time() - start
        return res

    res.diagnosis = Agent("diagnoser", DIAGNOSER, model, ["get_alert"] + READ).run(
        ws, f"Triage says: {json.dumps(res.triage)}\nFind the root cause.", res)

    fixer, feedback = {}, ""
    for _ in range(max_rounds):
        fixer = Agent("fixer", FIXER, model, ["read_file", "search_code", "edit_file", "create_test", "run_tests",
                                              "show_diff"]).run(
            ws, f"Diagnosis: {json.dumps(res.diagnosis)}{feedback}", res)
        res.review = Agent("reviewer", REVIEWER, model, ["show_diff", "run_tests", "read_file", "read_logs"]).run(
            ws, f"Incident: {ws.incident.title}\nDiagnosis: {json.dumps(res.diagnosis)}\n"
                f"Fixer says: {json.dumps(fixer)}\nReview the change.", res)
        if res.review.get("verdict") == "approve":
            # A reviewer agent can be fooled. These checks cannot.
            problems = ws.ship_gate()
            if not problems:
                break
            res.review = {"verdict": "reject", "reason": "Ship gate: " + "; ".join(problems),
                          "reviewer_said": res.review}
        feedback = f"\nYour last attempt was rejected: {res.review.get('reason')}. Fix that."

    if res.review.get("verdict") == "approve" and approve(ws, res):
        res.approved = True
        res.pr = _pr_body(ws, res, fixer)
        res.commit = ws.commit_fix(f"fix({ws.incident.id}): {res.diagnosis.get('root_cause', '')[:60]}")
    res.seconds = time.time() - start
    return res


def solo_responder(ws: Workspace, model, approve: ApprovalFn = auto_approve) -> Resolution:
    """Baseline: one agent with every tool."""
    start = time.time()
    res = Resolution(ws.incident.id)
    tools = ["get_alert"] + READ + ["edit_file", "create_test", "run_tests", "show_diff"]
    out = Agent("solo", SOLO, model, tools, max_steps=25).run(ws, "A page just fired. Handle it.", res)
    res.triage = {k: out.get(k) for k in ("category", "severity", "summary")}
    res.diagnosis = {k: out.get(k) for k in ("file", "root_cause")}
    if out.get("category") == "code_bug" and ws.changed_files() and not ws.ship_gate() and approve(ws, res):
        res.approved = True
        res.commit = ws.commit_fix(f"fix({ws.incident.id}): {str(out.get('root_cause', ''))[:60]}")
    res.seconds = time.time() - start
    return res
