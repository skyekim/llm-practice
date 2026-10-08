"""Exercise 6, step 3: run every case in cases.json through the agent and grade
the answers with code-based checks.

Each case passes only if every check passes:
- must_include:     every item appears in the answer, ignoring case
- must_not_include: no item appears in the answer
- unanswerable:     the answer says the data doesn't have it
- expected_tools:   each listed tool was called at least once

The agent runs without memory and with every write denied (run_agent's
defaults), so the evals can't change the applications table.

Usage, from the repo root:
    python 06-evals/run_evals.py                  # every case
    python 06-evals/run_evals.py visa remote      # only these ids
    python 06-evals/run_evals.py --verbose        # show the agent's rounds and tool calls
"""
import argparse
import contextlib
import io
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

EVALS_DIR = Path(__file__).parent
# The agent lives in 05-agent, which can't be imported as a package (it starts
# with a digit), so put that folder on the path. Its own imports, like tools
# and db, then resolve too.
sys.path.insert(0, str(EVALS_DIR.parent / "05-agent"))
from agent import run_agent  # noqa: E402

CASES_PATH = EVALS_DIR / "cases.json"
RESULTS_DIR = EVALS_DIR / "results"

# Ways the agent says the data doesn't have an answer. Matched after
# lowercasing and straightening curly apostrophes.
NOT_IN_DATA_PHRASES = [
    "doesn't", "does not", "don't", "do not", "isn't", "is not",
    "not listed", "not mentioned", "not specified", "not stated", "not included",
    "not provided", "not available", "no mention", "no information", "no details",
    "unable to find", "couldn't find", "could not find",
]


def normalize(text: str) -> str:
    return text.lower().replace("’", "'")


def mentions(text: str, term: str) -> bool:
    """True if term appears in text as a whole word, ignoring case.

    Whole words, so "sola" doesn't match "isolation" and "current" doesn't
    match "currently". A plural "s" is allowed ("visas" counts as "visa").
    Numbers only need non-digit neighbors, so "160" matches "$160K" and
    "$160,000" but not "1600". Terms that start or end with a symbol, like "$",
    aren't bounded on that side.
    """
    pattern = re.escape(normalize(term))
    if term[0].isalpha():
        pattern = r"(?<![a-z])" + pattern
    elif term[0].isdigit():
        pattern = r"(?<!\d)" + pattern
    if term[-1].isalpha():
        pattern += r"s?(?![a-z])"
    elif term[-1].isdigit():
        pattern += r"(?!\d)"
    return re.search(pattern, normalize(text)) is not None


def check(case: dict, result: dict) -> list[str]:
    """Return why the case failed, one line per failed check; empty if it passed."""
    if result["outcome"] != "answer":
        return [f"no answer: {result['error']}"]

    answer = result["answer"]
    failures = []

    missing = [t for t in case["must_include"] if not mentions(answer, t)]
    if missing:
        failures.append(f"missing: {', '.join(missing)}")

    forbidden = [t for t in case["must_not_include"] if mentions(answer, t)]
    if forbidden:
        failures.append(f"included: {', '.join(forbidden)}")

    if case["category"] == "unanswerable":
        if not any(p in normalize(answer) for p in NOT_IN_DATA_PHRASES):
            failures.append("didn't say the data doesn't have it")

    called = {c["name"] for c in result["tool_calls"]}
    not_called = [t for t in case.get("expected_tools", []) if t not in called]
    if not_called:
        failures.append(f"didn't call: {', '.join(not_called)}")

    return failures


def main():
    parser = argparse.ArgumentParser(description="Run the agent evals.")
    parser.add_argument("ids", nargs="*", help="only run these case ids")
    parser.add_argument("--verbose", action="store_true",
                        help="show the agent's own output (rounds and tool calls)")
    args = parser.parse_args()

    cases = json.loads(CASES_PATH.read_text())
    if args.ids:
        unknown = set(args.ids) - {c["id"] for c in cases}
        if unknown:
            sys.exit(f"Unknown case ids: {', '.join(sorted(unknown))}")
        cases = [c for c in cases if c["id"] in args.ids]

    records = []
    for i, case in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] {case['id']}: {case['question']}", flush=True)
        # run_agent prints every round and tool call; hide that unless asked.
        with contextlib.redirect_stdout(sys.stdout if args.verbose else io.StringIO()):
            result = run_agent(case["question"])
        if result["outcome"] == "cancelled":
            print("Cancelled; stopping.")
            break

        failures = check(case, result)
        passed = not failures
        tools = ", ".join(c["name"] for c in result["tool_calls"]) or "none"
        print(f"  {'PASS' if passed else 'FAIL'}  {result['steps']} steps, "
              f"${result['cost']:.4f}, {result['seconds']}s  tools: {tools}")
        for failure in failures:
            print(f"        {failure}")
        records.append({"id": case["id"], "category": case["category"],
                        "question": case["question"], "passed": passed,
                        "failures": failures, **result})

    if not records:
        return

    # Summary by category, in the order categories first appear in cases.json.
    by_category = defaultdict(list)
    for r in records:
        by_category[r["category"]].append(r["passed"])
    print()
    for category, results in by_category.items():
        print(f"{category:<14} {sum(results)}/{len(results)}")
    passed = sum(r["passed"] for r in records)
    cost = sum(r["cost"] for r in records)
    seconds = sum(r["seconds"] for r in records)
    print(f"{'total':<14} {passed}/{len(records)} passed, ${cost:.4f}, {seconds:.0f}s")

    # Every answer and tool call, so runs can be compared after a change.
    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / f"{datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps({"passed": passed, "total": len(records), "cost": cost,
                                "seconds": seconds, "cases": records}, indent=2))
    print(f"Saved to {path}")


if __name__ == "__main__":
    main()
