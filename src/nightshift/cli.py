"""Command line: nightshift list | nightshift run INC-101"""
from __future__ import annotations

import argparse
import json

from .agents import ask_human, auto_approve, respond, solo_responder
from .evaluate import grade
from .incidents import BY_ID, INCIDENTS
from .llm import make_model
from .workspace import Workspace


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="nightshift", description="An AI on-call team with a human in the loop.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list the benchmark incidents")
    r = sub.add_parser("run", help="respond to one incident in a sandbox")
    r.add_argument("incident")
    r.add_argument("--provider", default="openai")
    r.add_argument("--model", default=None)
    r.add_argument("--solo", action="store_true", help="one agent with every tool, instead of the team")
    r.add_argument("--yes", action="store_true", help="skip the human approval prompt")
    r.add_argument("--trace", default=None, help="write every agent step to this JSON file")
    args = ap.parse_args(argv)

    if args.cmd == "list":
        for i in INCIDENTS:
            print(f"{i.id}  {i.kind:5s}  {i.title}")
        return
    ws = Workspace(BY_ID[args.incident.upper()])
    try:
        model = make_model(args.provider, args.model)
        approve = auto_approve if args.yes else ask_human
        res = (solo_responder if args.solo else respond)(ws, model, approve)
        for s in res.steps:
            print(f"  {s.agent:10s} -> {s.tool}({json.dumps(s.args)[:80]})")
        print("\nTriage:", res.triage)
        print("Diagnosis:", res.diagnosis)
        print("Review:", res.review)
        if res.pr:
            print("\n" + res.pr)
        print("\nGrade:", json.dumps(grade(ws, res), indent=2))
        if args.trace:
            open(args.trace, "w").write(json.dumps(res.to_dict(), indent=2))
    finally:
        ws.close()


if __name__ == "__main__":
    main()
