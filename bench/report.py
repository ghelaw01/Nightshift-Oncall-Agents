"""Summarize Night Shift benchmark results into bench/results/summary.md."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

RESULTS = Path(__file__).parent / "results"


def pct(a, b):
    return f"{a}/{b} ({100 * a / b:.0f}%)" if b else "-"


def main():
    lines = ["| Model | Design | Resolved | Real bugs fixed and shipped | Noise left alone | Root cause file | "
             "Regression test catches the bug | Bad fixes shipped | Guardrail blocks | Tokens / incident |",
             "| --- " * 10 + "|"]
    per_incident = defaultdict(lambda: defaultdict(int))
    for path in sorted(RESULTS.glob("*.jsonl")):
        rows = [json.loads(l) for l in path.read_text().splitlines()]
        for design in ("team", "solo"):
            mine = [r for r in rows if r["design"] == design and "grade" in r]
            if not mine:
                continue
            g = [r["grade"] for r in mine]
            bugs = [x for x in g if x["kind"] == "bug"]
            noise = [x for x in g if x["kind"] == "noise"]
            tokens = sum(r["resolution"]["input_tokens"] + r["resolution"]["output_tokens"] for r in mine) / len(mine)
            lines.append(" | ".join([
                f"| {path.stem}", design, pct(sum(x["resolved"] for x in g), len(g)),
                pct(sum(x["resolved"] for x in bugs), len(bugs)), pct(sum(x["resolved"] for x in noise), len(noise)),
                pct(sum(x.get("root_cause_file_ok", False) for x in bugs), len(bugs)),
                pct(sum(x.get("regression_test_catches_bug", False) for x in bugs), len(bugs)),
                str(sum(x.get("bad_fix_shipped", False) for x in bugs)),
                str(sum(len(x["violations"]) for x in g)), f"{tokens:,.0f} |"]))
            for r in mine:
                per_incident[(r["incident"])][design] += r["grade"]["resolved"]
                per_incident[(r["incident"])][design + "_n"] += 1
    lines += ["", "| Incident | Team resolved | Solo resolved |", "| --- | --- | --- |"]
    for inc in sorted(per_incident):
        d = per_incident[inc]
        lines.append(f"| {inc} | {d['team']}/{d['team_n']} | {d['solo']}/{d['solo_n']} |")
    text = "\n".join(lines) + "\n"
    (RESULTS / "summary.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
