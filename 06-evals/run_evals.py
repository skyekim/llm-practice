"""Exercise 6, step 3: run every case in cases.json through the agent and grade
the answers with code-based checks.

Each case passes only if every check passes:
- must_include:     every item appears in the answer, ignoring case
- must_not_include: no item appears in the answer
- unanswerable:     the answer says the data doesn't have it
- expected_tools:   each listed tool was called at least once
- must_not_call:    none of these tools was called, even if the call was denied
- max_tool_calls:   no more than this many tool calls
- rubric:           an LLM judge (judge.py) says the answer meets it

A case can also set:
- turns:      earlier questions asked first in the same history; only the
              last question is graded
- fail_tools: {tool: "always" | "first"}, making those tools raise a
              connection error on every call or only the first, during the
              graded question

The agent runs without memory and with every write denied (run_agent's
defaults), so the evals can't change the applications table.

Usage, from the repo root:
    python 06-evals/run_evals.py --label baseline          # every case, saved to results/baseline.json
    python 06-evals/run_evals.py --case visa --case remote # only these ids
    python 06-evals/run_evals.py --verbose                 # show the agent's rounds and tool calls
    python 06-evals/run_evals.py --cases 07-harness/cases.json --label baseline

Results go in a results folder next to the case file, so 07-harness's runs
are saved in 07-harness/results. Without --label, they're saved under a
timestamp, so debugging runs don't overwrite a labeled one.
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
from agent import MODEL, run_agent  # noqa: E402
from judge import judge  # noqa: E402
# The same dict the agent looks tools up in, so replacing an entry here
# changes what the agent's call runs.
from tools import TOOL_FUNCTIONS  # noqa: E402

REPO_ROOT = EVALS_DIR.parent
FAIL_MODES = ("always", "first")

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

    wrongly_called = [t for t in case.get("must_not_call", []) if t in called]
    if wrongly_called:
        failures.append(f"called: {', '.join(wrongly_called)}")

    max_calls = case.get("max_tool_calls")
    if max_calls is not None and len(result["tool_calls"]) > max_calls:
        failures.append(f"{len(result['tool_calls'])} tool calls, over the limit of {max_calls}")

    return failures


@contextlib.contextmanager
def failing_tools(modes: dict):
    """Make the named tools raise a connection error, as if the database were
    down: "always" fails every call, "first" only the first, so a retry works.
    The real functions are put back afterwards."""
    originals = {name: TOOL_FUNCTIONS[name] for name in modes}

    def failing(name, fn, mode):
        calls = 0

        def wrapper(**kwargs):
            nonlocal calls
            calls += 1
            if mode == "always" or calls == 1:
                raise ConnectionError(f"could not connect to the database for {name}")
            return fn(**kwargs)
        return wrapper

    for name, mode in modes.items():
        TOOL_FUNCTIONS[name] = failing(name, originals[name], mode)
    try:
        yield
    finally:
        TOOL_FUNCTIONS.update(originals)


def run_case(case: dict, verbose: bool) -> tuple[dict, list[str]]:
    """Ask the case's earlier turns, then its question, in one history.

    Returns the question's result and why any earlier turn failed. Its cost,
    steps, seconds, and tokens include the earlier turns, so a case costs what
    the whole conversation did; its tool_calls are the question's own.
    """
    messages = []
    turns = case.get("turns", [])
    earlier = {"cost": 0.0, "steps": 0, "seconds": 0.0, "input_tokens": 0, "output_tokens": 0}
    earlier_failures = []
    # run_agent prints every round and tool call; hide that unless asked.
    with contextlib.redirect_stdout(sys.stdout if verbose else io.StringIO()):
        for turn, question in enumerate(turns, 1):
            result = run_agent(question, messages, turn=turn)
            if result["outcome"] == "cancelled":
                return result, []
            if result["outcome"] != "answer":
                earlier_failures.append(f"turn {turn} failed: {result['error']}")
            for key in earlier:
                earlier[key] += result[key]
        with failing_tools(case.get("fail_tools", {})):
            result = run_agent(case["question"], messages, turn=len(turns) + 1)
    for key in earlier:
        result[key] += earlier[key]
    result["seconds"] = round(result["seconds"], 2)
    return result, earlier_failures


def main():
    parser = argparse.ArgumentParser(description="Run the agent evals.")
    parser.add_argument("--cases", default="06-evals/cases.json", metavar="PATH",
                        help="case file, from the repo root (default: 06-evals/cases.json)")
    parser.add_argument("--case", action="append", default=[], metavar="ID",
                        help="only run this case id; repeat to run several")
    parser.add_argument("--label",
                        help="name for this version, e.g. baseline; saves to results/<label>.json")
    parser.add_argument("--verbose", action="store_true",
                        help="show the agent's own output (rounds and tool calls)")
    args = parser.parse_args()

    cases_path = REPO_ROOT / args.cases
    cases = json.loads(cases_path.read_text())
    for case in cases:
        unknown_tools = set(case.get("fail_tools", {})) - set(TOOL_FUNCTIONS)
        bad_modes = set(case.get("fail_tools", {}).values()) - set(FAIL_MODES)
        if unknown_tools or bad_modes:
            sys.exit(f"{case['id']}: bad fail_tools (tools must be in TOOL_FUNCTIONS, "
                     f"modes one of {', '.join(FAIL_MODES)})")
    if args.case:
        unknown = set(args.case) - {c["id"] for c in cases}
        if unknown:
            sys.exit(f"Unknown case ids: {', '.join(sorted(unknown))}")
        cases = [c for c in cases if c["id"] in args.case]

    records = []
    for i, case in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] {case['id']}: {case['question']}", flush=True)
        result, earlier_failures = run_case(case, args.verbose)
        if result["outcome"] == "cancelled":
            print("Cancelled; stopping.")
            break

        failures = earlier_failures + check(case, result)
        # The judge only grades real answers; check() already failed the rest.
        verdict = None
        if case.get("rubric") and result["outcome"] == "answer":
            verdict = judge(case["question"], result["answer"], case["rubric"])
            if not verdict["pass"]:
                failures.append(f"judge: {verdict['reason']}")
        passed = not failures
        tools = ", ".join(c["name"] for c in result["tool_calls"]) or "none"
        print(f"  {'PASS' if passed else 'FAIL'}  {result['steps']} steps, "
              f"${result['cost']:.4f}, {result['input_tokens']:,} tokens in, "
              f"{result['seconds']}s  tools: {tools}")
        for failure in failures:
            print(f"        {failure}")
        # Print passing verdicts too, so they can be checked by hand.
        if verdict and verdict["pass"]:
            print(f"        judge: {verdict['reason']}")
        records.append({"id": case["id"], "category": case["category"],
                        "question": case["question"], "passed": passed,
                        "failures": failures, "judge": verdict, **result})

    if not records:
        return

    # One row per case.
    id_width = max(len(r["id"]) for r in records)
    cat_width = max(len(r["category"]) for r in records)
    print()
    print(f"{'case':<{id_width}}  {'category':<{cat_width}}  result  {'cost':>7}  steps  "
          f"calls  {'tokens in':>9}  {'time':>5}")
    for r in records:
        print(f"{r['id']:<{id_width}}  {r['category']:<{cat_width}}  "
              f"{'PASS' if r['passed'] else 'FAIL':<6}  ${r['cost']:.4f}  "
              f"{r['steps']:>5}  {len(r['tool_calls']):>5}  {r['input_tokens']:>9,}  "
              f"{r['seconds']:>4.0f}s")

    # Pass rate by category, in the order categories first appear in cases.json.
    by_category = defaultdict(list)
    for r in records:
        by_category[r["category"]].append(r["passed"])
    print()
    for category, results in by_category.items():
        print(f"{category:<14} {sum(results)}/{len(results)}  "
              f"{sum(results) / len(results):.0%}")
    passed = sum(r["passed"] for r in records)
    # Per-case cost is the agent's; the judge's calls are counted separately.
    judge_cost = sum(r["judge"]["cost"] for r in records if r["judge"])
    cost = sum(r["cost"] for r in records) + judge_cost
    seconds = sum(r["seconds"] for r in records)
    avg_steps = sum(r["steps"] for r in records) / len(records)
    avg_seconds = seconds / len(records)
    avg_tool_calls = sum(len(r["tool_calls"]) for r in records) / len(records)
    input_tokens = sum(r["input_tokens"] for r in records)
    avg_input_tokens = input_tokens / len(records)
    print(f"{'total':<14} {passed}/{len(records)}  {passed / len(records):.0%}")
    print(f"\nTotal cost ${cost:.4f} (judge ${judge_cost:.4f}), average "
          f"{avg_steps:.1f} steps, {avg_tool_calls:.1f} tool calls, "
          f"{avg_input_tokens:,.0f} tokens in, and {avg_seconds:.1f}s per case")

    # Every answer and tool call, so runs can be compared after a change.
    label = args.label or f"{datetime.now():%Y%m%d-%H%M%S}"
    results_dir = cases_path.parent / "results"
    results_dir.mkdir(exist_ok=True)
    path = results_dir / f"{label}.json"
    path.write_text(json.dumps({
        "label": label,
        "case_file": args.cases,
        "model": MODEL,
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "passed": passed, "total": len(records), "pass_rate": passed / len(records),
        "by_category": {c: {"passed": sum(rs), "total": len(rs)}
                        for c, rs in by_category.items()},
        "cost": cost, "judge_cost": judge_cost, "seconds": seconds,
        "avg_steps": avg_steps, "avg_seconds": avg_seconds,
        "avg_tool_calls": avg_tool_calls,
        "input_tokens": input_tokens, "avg_input_tokens": avg_input_tokens,
        "cases": records,
    }, indent=2))
    print(f"Saved to {path}")


if __name__ == "__main__":
    main()
