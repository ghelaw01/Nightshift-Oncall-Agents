"""Benchmark: 8 real regressions + 2 noise alerts, graded against hidden tests.

    python bench/run_bench.py --models gpt-4.1-mini gpt-5.4-mini --runs 3
"""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from nightshift import INCIDENTS, Workspace, grade, make_model, respond, solo_responder

OUT = Path(__file__).parent / "results"


def run_one(incident, design, model, run):
    ws = Workspace(incident)
    try:
        for attempt in range(3):
            try:
                res = (respond if design == "team" else solo_responder)(ws, model)
                break
            except Exception as e:     # rate limits: wait and retry on a fresh sandbox
                if attempt == 2:
                    return {"incident": incident.id, "design": design, "run": run, "error": str(e)}
                ws.close()
                ws = Workspace(incident)
                time.sleep(15 * (attempt + 1))
        return {"incident": incident.id, "design": design, "run": run, "grade": grade(ws, res),
                "resolution": res.to_dict(), "diff": ws.show_diff()}
    finally:
        ws.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="openai")
    ap.add_argument("--models", nargs="+", default=["gpt-4.1-mini"])
    ap.add_argument("--designs", nargs="+", default=["team", "solo"])
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--concurrency", type=int, default=6)
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    for name in args.models:
        model = make_model(args.provider, name)
        jobs = [(i, d, r) for d in args.designs for r in range(args.runs) for i in INCIDENTS]
        t0 = time.time()
        with ThreadPoolExecutor(args.concurrency) as pool:
            rows = list(pool.map(lambda j: run_one(j[0], j[1], model, j[2]), jobs))
        (OUT / f"{name}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        for d in args.designs:
            mine = [r for r in rows if r["design"] == d and "grade" in r]
            ok = sum(r["grade"]["resolved"] for r in mine)
            bad = sum(r["grade"].get("bad_fix_shipped", False) for r in mine)
            print(f"{name:14s} {d:5s} resolved {ok}/{len(mine)}  bad fixes shipped {bad}  "
                  f"errors {sum(r['design'] == d and 'error' in r for r in rows)}")
        print(f"  ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
