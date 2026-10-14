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

## Step 2: Batch tool (get_all_postings_detail)

### What changed

Added `get_all_postings_detail()` in `tools.py`: one call returning full
details (skills, salary, years, application status) for every posting,
replacing the per-posting `get_posting` loop the agent used for "list
everything" questions. Added a system-prompt line telling the model to
prefer it over calling `get_posting` repeatedly. Also added a line telling
the model to treat "unlimited vacation" and "unlimited PTO" as the same
thing, after `all-postings-table` and `python-200k-fit` both
mis-scored Guac's benefit (seen in the global-search chunk) as not counting.

### Results

| | search-fixed-baseline | batch-tool-v2 |
| --- | --- | --- |
| Pass rate | 12/15 (80%) | 11/15 (73%) |
| Total cost | $0.2625 | $0.2493 |
| Avg tool calls | 4.87 | 3.2 |
| Avg input tokens | 13,283 | 12,789 |

Tool calls dropped ~34% and cost dropped, confirming the batch tool fixed
the inefficiency `trim_old_tool_results` could only paper over. `all-
postings-table` \u2014 the worst-performing case from the very first
baseline \u2014 now passes outright for the first time.

The lower headline pass rate is mostly test staleness, not new bugs:

- `unapplied-overview`: judge confirmed the content was correct; the
  failure was only `expected_tools` still naming `get_applications`, which
  `get_all_postings_detail` now makes redundant for this case. Needs
  updating in `cases.json`.
- `applied-top-salary-interviews`: judge passed it; `must_include` failed
  only because this run didn't restate the exact salary figure in text.

One real regression: `which-backend-job` now lists all 6 postings with
"backend" in the title instead of just the 3 the user has applied to or
saved, because the agent reached for `search_postings` instead of
`get_applications` first. Left as a known issue \u2014 the system prompt's
batch-tool nudge may need to be scoped more narrowly to "list all
postings" questions rather than "my application" questions.

### Decision

Keep the batch tool and the PTO-synonym fix; they're a clear net
improvement on cost and call count with one real behavioral regression
to watch. Trimming (`trim_old_tool_results`) stays disabled per the step 1
re-evaluation above \u2014 the batch tool addressed the root inefficiency
trimming was compensating for.