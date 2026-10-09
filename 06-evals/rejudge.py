"""Re-grade saved answers with the current judge and rubrics, without running
the agent again. The answers stay the same, so a changed verdict comes from
the judge or rubric change alone.

Usage, from the repo root:
    python 06-evals/rejudge.py judge-check-1 judge-check-2          # every judged case
    python 06-evals/rejudge.py judge-check-1 judge-check-2 --case remote
    python 06-evals/rejudge.py baseline --cases 07-harness/cases.json

Rubrics come from the case file and labels from the results folder next to it,
as in run_evals.py.
"""
import argparse
import json
from pathlib import Path

from judge import judge

REPO_ROOT = Path(__file__).parent.parent


def main():
    parser = argparse.ArgumentParser(description="Re-judge saved eval answers.")
    parser.add_argument("labels", nargs="+", help="results/<label>.json files to re-judge")
    parser.add_argument("--case", action="append", default=[], metavar="ID",
                        help="only re-judge this case id; repeat for several")
    parser.add_argument("--cases", default="06-evals/cases.json", metavar="PATH",
                        help="case file, from the repo root (default: 06-evals/cases.json)")
    args = parser.parse_args()

    cases_path = REPO_ROOT / args.cases
    results_dir = cases_path.parent / "results"
    rubrics = {c["id"]: c["rubric"]
               for c in json.loads(cases_path.read_text()) if c.get("rubric")}

    cost = 0.0
    for label in args.labels:
        for r in json.loads((results_dir / f"{label}.json").read_text())["cases"]:
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
