"""Re-grade saved answers with the current judge and rubrics, without running
the agent again. The answers stay the same, so a changed verdict comes from
the judge or rubric change alone.

Usage, from the repo root:
    python 06-evals/rejudge.py judge-check-1 judge-check-2          # every judged case
    python 06-evals/rejudge.py judge-check-1 judge-check-2 --case remote
"""
import argparse
import json
from pathlib import Path

from judge import judge

EVALS_DIR = Path(__file__).parent
RESULTS_DIR = EVALS_DIR / "results"


def main():
    parser = argparse.ArgumentParser(description="Re-judge saved eval answers.")
    parser.add_argument("labels", nargs="+", help="results/<label>.json files to re-judge")
    parser.add_argument("--case", action="append", default=[], metavar="ID",
                        help="only re-judge this case id; repeat for several")
    args = parser.parse_args()

    rubrics = {c["id"]: c["rubric"]
               for c in json.loads((EVALS_DIR / "cases.json").read_text()) if c.get("rubric")}

    cost = 0.0
    for label in args.labels:
        for r in json.loads((RESULTS_DIR / f"{label}.json").read_text())["cases"]:
            if r["id"] not in rubrics or (args.case and r["id"] not in args.case):
                continue
            if not r["answer"]:
                continue
            old = r.get("judge")
            v = judge(r["question"], r["answer"], rubrics[r["id"]])
            cost += v["cost"]
            before = "none" if not old else ("PASS" if old["pass"] else "FAIL")
            print(f"{label} {r['id']}: was {before}, now {'PASS' if v['pass'] else 'FAIL'}")
            print(f"    {v['reason']}")
    print(f"\nJudge cost ${cost:.4f}")


if __name__ == "__main__":
    main()
