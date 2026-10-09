# 07 – Harness Engineering

Improving the harness around the job search agent: the code in
`../05-agent/agent.py` that runs the tool loop, manages the history, and
handles limits and errors. The model and tools stay the same.

- `cases.json`: 15 harder cases the exercise 6 cases don't cover, in five
  categories: long (many postings or chained tools), multi-turn, tool-error,
  guardrail, and ambiguous. They use four fields added to
  `../06-evals/run_evals.py` for this exercise:
  - `turns`: earlier questions asked first in the same history; only the last
    question is graded, but cost and steps include the whole conversation
  - `fail_tools`: `{tool: "always" | "first"}` makes a tool raise a connection
    error on every call, or only the first so a retry works
  - `must_not_call`: tools that must not be called, even if the call was denied
  - `max_tool_calls`: an upper limit on tool calls, to catch wasted calls

Run them from the repo root with
`python 06-evals/run_evals.py --cases 07-harness/cases.json --label baseline`.
Results are saved to `07-harness/results/<label>.json`. The 22 exercise 6
cases still run with `python 06-evals/run_evals.py`, as a check that harness
changes don't break them.
