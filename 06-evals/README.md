# 06 – Evals

Automated tests for the job search agent from exercise 5: a fixed set of
questions with known answers, run through the agent and graded by code.

- `../05-agent/agent.py`: the tool loop is now `run_agent(question)`, which
  returns the answer, tool calls, steps, cost, and seconds. By default it runs
  without memory and denies every `update_application` call, so evals can't
  change the applications table. The chat is a thin wrapper around it.
- `cases.json`: 22 cases in six categories (structured, text, multi-step,
  unanswerable, tricky, open-ended), each with a question, `must_include` and
  `must_not_include` strings, the tools it should call, notes on where the
  expected answer comes from, and for four cases a `rubric` for the judge
- `check_data.py`: prints the applications, skills, years, and salaries the
  expected answers rely on, to check them against the database
- `judge.py`: an LLM judge for open-ended answers. A second API call grades
  the answer against the case's `rubric`, forcing a `record_verdict` tool call
  (like exercise 2's approach B) to get `{"pass": bool, "reason": str}`
- `rejudge.py`: re-grades saved answers in `results/<label>.json` with the
  current judge and rubrics, without running the agent, so a changed verdict
  comes from the judge or rubric alone
- `run_evals.py`: runs every case and grades it with code-based checks, then
  prints a table of each case's result, cost, and steps, with pass rates by
  category, total cost, and average steps and time. It saves every answer and
  tool call to `results/<label>.json`.

Run it from the repo root with `python 06-evals/run_evals.py --label baseline`.
Pass `--case <id>` (repeatable) to run only those cases, and `--verbose` to see
the agent's rounds and tool calls. Without `--label`, results are saved under a
timestamp. Set `AGENT_MODEL` to run the agent on another model, e.g.
`AGENT_MODEL=claude-sonnet-5-5 python 06-evals/run_evals.py --label sonnet`;
each results file records the model it ran on.

## Checks

A case passes only if every check passes:

- **must_include**: every item appears in the answer, as a whole word and
  ignoring case, so "sola" doesn't match "isolation" and "current" doesn't
  match "currently". Numbers only need non-digit neighbors, so "160" matches
  "$160K".
- **must_not_include**: no item appears in the answer.
- **Unanswerable cases**: the answer says the data doesn't have it ("doesn't",
  "not listed", "not mentioned"…).
- **expected_tools**: each listed tool was called at least once.
- **rubric**: for cases that have one, the LLM judge says the answer meets it.
  The judge's reason is printed whether the case passes or fails, so its
  verdicts can be checked by hand.

## Results

### Baseline

I ran all 20 cases three times. Each run cost about $0.14 and took about 80
seconds.

| Case | Run 1 | Run 2 | Run 3 | What it is |
| --- | --- | --- | --- | --- |
| 16 other cases | ✓ | ✓ | ✓ | Stable passes |
| `unlimited-pto` | ✗ | ✗ | ✗ | Stable failure: text search never finds Guac |
| `edra-interviews` | ✗ | ✓ | ✓ | Flaky: sometimes answers without calling a tool |
| `visa` | ✓ | ✓ | ✗ | Flaky: sometimes guesses beyond the data |

Run 1 also failed `applications-python` and `hazel-pto`, but those were
mistakes in my cases (below), fixed before runs 2 and 3. The baseline is 18 to
19 of 20.

| Category | Run 2 | Run 3 |
| --- | --- | --- |
| Structured | 5/5 | 5/5 |
| Text | 4/5 | 3/5 |
| Multi-step | 4/4 | 4/4 |
| Unanswerable | 3/3 | 3/3 |
| Tricky | 3/3 | 3/3 |
| **Total** | **19/20** | **18/20** |

### The agent's failures

- **Retrieval missed an answer (`unlimited-pto`, every run).** Searching
  "unlimited PTO vacation" returned 10 chunks, but not Guac's "Unlimited
  vacation days". The only Guac chunk was its "in-person 5 days a week" note.
  The model answered correctly from what it got, so this is a search problem,
  not a reasoning one.
- **Saying something isn't there without checking (`edra-interviews`, 1 of
  3).** It answered "I don't have information about a company called 'Edra'"
  with no tool calls, though the system prompt says to check with a tool
  first. The same mistake happened in exercise 5 with "Brevel". This answer
  passed the unanswerable check (it contains "don't") and would have passed
  must_include if the case had one. Only the `expected_tools` check caught it.
- **Guessing beyond the data (`visa`, 1 of 3).** It correctly named Bevel, then
  added that Mistral's "relocation support … may include visa-related
  assistance", which nothing in the data says.

Two of these three only showed up in some runs. A single run would have
called the agent either better or worse than it is.

### Mistakes in my cases

Reading the failures showed that some came from the cases, not the agent:

- **The data changed.** `check_data.py` showed a fourth application (Sola,
  applied 2026-10-08) that wasn't in the seed data. `applications-python`
  needed Sola added to `must_include`.
- **Penalizing explanations.** For `applications-python`, the answer listed
  Sola, Bevel, and Guac, then said "Giga… doesn't include Python". That's a
  good answer, but `must_not_include: ["giga"]` failed it. `must_not_include`
  only works for companies a correct answer has no reason to mention.
- **Requiring a name the answer doesn't need.** For `hazel-pto`, the answer
  said "the job posting doesn't specify PTO" without naming Hazel, which failed
  `must_include: ["hazel"]`. I removed company names from all three
  unanswerable cases.
- **The task's example was incomplete.** It listed Mistral and Sola for
  Kubernetes, but Lorum and OpenAI have the skill too.

### What string checks can't grade

- **Qualifications.** `unlimited-pto` answers listed Lorum and Sola with "(not
  explicitly unlimited)". The check sees the names, not the caveat.
- **`remote`.** "Hazel is hybrid, not remote" and "Hazel is remote" contain
  the same words, so this case has no strings and is graded only on its tool
  call. Its answers said none are fully remote, which is right, but one run
  never mentioned Hazel and ended by offering to check the rest.
- **Unanswerable cases.** Any "does not" passes, even in an answer that also
  invents something. `must_not_include` (like `"$"` for Mistral's salary) is
  the backstop.

### Cost of a question

Most cases took 2 steps and about $0.005. The expensive ones show where the
tools are missing something:

- `years-3-plus` made 11 to 12 `get_posting` calls, one per posting, because
  `search_postings` only has `max_years`. It cost $0.012 to $0.014, about 2.5
  times a typical case.
- `remote` sometimes fetched every posting too, for $0.017.

### LLM judge

Three cases have a rubric: `remote`, which string checks can't grade, and two
new open-ended comparisons, `compare-giga-sola` and `compare-edra-guac`. I
checked six verdicts (three cases, two runs) against my own reading of the
answers.

- **First runs graded nothing.** Postgres wasn't running, so every tool call
  failed and the agent answered "I can't access the database". The judge failed
  all six, correctly, but that didn't test it. The string checks alone could
  have passed answers like that on an unanswerable case.
- **5 of 6 matched my reading.** The comparisons passed, and they were right.
  The miss was a `remote` answer saying the results "don't show any postings
  that explicitly mention being fully remote". The rubric passes that, but the
  judge failed it for not covering "all six postings".
- **Telling the judge didn't fix it.** I added "Don't require anything the
  rubric doesn't ask for" to its system prompt and "The answer doesn't need to
  mention every posting" to the rubric. Re-judging the same saved answers
  (`rejudge.py`) still failed both, for leaving out Hazel and Oso.
- **Removing the facts did.** The rubric listed every posting's office policy
  as background. Haiku treated each fact as something the answer had to
  mention. Once the rubric had only the pass and fail criteria, both `remote`
  answers passed.
- **Vague wording gave inconsistent verdicts.** The Giga rubric said "1-3
  years". The judge failed one "1+ years" answer while admitting it was
  "technically within that range", and passed an identical one. Listing the
  accepted wordings ("1-3 years", "1+ years", "at least 1 year") fixed it.
- **Still lenient on borderline answers.** One `remote` answer listed four
  in-office postings and never said none are remote. The judge passed it,
  saying it "correctly states that no postings are fully remote".

A judge follows a rubric's wording more closely than its meaning. A rubric
should state only what passes and what fails, and keep supporting facts in
`notes`.

### Baseline with the runner and judge

`python 06-evals/run_evals.py --label baseline`, saved to
`results/baseline.json`.

| Category | Result |
| --- | --- |
| Structured | 5/5 |
| Text | 4/5 |
| Multi-step | 4/4 |
| Unanswerable | 3/3 |
| Tricky | 3/3 |
| Open-ended | 2/2 |
| **Total** | **21/22 (95%)** |

Total cost $0.17 (the judge was $0.005 of it), an average of 2.6 steps and 4.5
seconds per case.

The only failure is `unlimited-pto` again, and it's half the agent's fault:

- **Missing Guac** is the same retrieval miss as before. One search, and Guac's
  "Unlimited vacation days" chunk wasn't in the results.
- **Including Lorum** is a mistake in the case. The answer separated Lorum
  out as "a flexible vacation policy", not unlimited, but `must_not_include`
  only sees the name. After this run I replaced the Sola, Edra, and Lorum
  strings with a rubric, so the judge grades that distinction.

The most expensive cases were `edra-interviews` ($0.017, 5 steps),
`300k-in-office` ($0.016), and `years-3-plus` ($0.015, 11 `get_posting` calls).

## Improving the agent

Each version changes one thing and keeps the ones before it. Targeted cases
were run several times on their own (`--case`) before a full run, since a
case that passes once can still be flaky.

### Versions

| Label | What changed | Pass rate | Cost | Avg steps |
| --- | --- | --- | --- | --- |
| `baseline` | Nothing | 21/22 (95%) | $0.175 | 2.6 |
| `baseline-2` | Nothing (rerun) | 21/22 (95%) | $0.167 | 2.5 |
| `baseline-3` | Nothing (rerun) | 21/22 (95%) | $0.167 | 2.5 |
| `rag-k-20` | Text search returns 20 chunks, not 10 | 22/22 (100%) | $0.184 | 2.5 |
| `min-years` | `search_postings` gets a `min_years` filter and returns `min_years` | 21/22 (95%) | $0.162 | 2.3 |
| `tool-first` | System prompt: always call a tool before answering about a company | 22/22 (100%) | $0.166 | 2.4 |

Costs include the judge, about $0.006 a run. The `unlimited-pto` case changed
between `baseline` and `baseline-2` (strings replaced by a rubric), so its
failure in `baseline` is partly the case's fault; it failed all three baseline
runs on the missing Guac either way.

- **`rag-k-20`** fixed the one stable failure. `unlimited-pto` passed 3 of 3
  targeted runs and the full run, after failing every baseline run. With 10
  chunks, Guac's "Unlimited vacation days" never made it into the results. It
  costs about 10% more, because every text search now sends twice the text.
- **`min-years`** fixed cost, not correctness. `years-3-plus` went from 3–4
  steps, 11 `get_posting` calls, and $0.012–0.015 to 2 steps, one search, and
  $0.005, in 3 of 3 runs. `300k-in-office` and `compare-edra-guac` also
  dropped their `get_posting` calls. The run's one failure was
  `edra-interviews` answering without a tool, which is the flaky case below,
  not this change: it made no tool calls at all.
- **`tool-first`** fixed that flake. `edra-interviews` passed 2 of 3 targeted
  runs under `min-years`, then 6 of 6 (five targeted runs plus the full run)
  after the prompt change. The old line, "Check with a tool before saying
  something isn't in the data", was there all along; the model skipped it when
  it didn't recognize "Edra". The new one says why: it doesn't know which
  companies are saved until it searches.

### Which change helped most

For correctness, `rag-k-20`: it took the pass rate from 95% to 100% by fixing
the only case that failed every time. For cost, `min-years`: it cut the most
expensive structured case by about 65% and the full run from $0.184 to $0.162
(12%), which more than paid for `rag-k-20`'s extra text. The final version,
`tool-first`, passes 22/22 for $0.166, less than the baseline's $0.167–0.175,
in 2.4 steps instead of 2.5–2.6.

### Most common causes of failure

Across every run in this exercise, in order of how often they came up:

1. **The expected answer was wrong.** The most common cause, and the easiest
   to miss: the eval was failing correct answers. Sola missing from
   `applications-python` after the data changed, `must_not_include` catching
   "Giga doesn't include Python" and "Lorum offers a flexible vacation
   policy", requiring Hazel's name in `hazel-pto`, an incomplete Kubernetes
   list, and rubrics the judge read too literally (below).
2. **Retrieval missed the passage.** `unlimited-pto`, every run until
   `rag-k-20`. The model answered correctly from what it got.
3. **Answering without a tool.** `edra-interviews` said "I don't have
   information about a company called 'Edra'" with no tool calls, about 1 run
   in 3 until `tool-first`. Only the `expected_tools` check caught it.
4. **Inventing something.** `visa` once added that Mistral's relocation
   support "may include visa-related assistance". It didn't happen again in
   the later runs.

Not a cause the exercise lists, but it cost two runs: Postgres wasn't running,
every tool call failed, and the agent answered "I can't access the database".

### Did the LLM judge agree with me?

Mostly, once the rubrics were right. I read every answer it graded in the
`judge-check` runs and the `unlimited-pto` re-judges:

| Round | Agreed | What went wrong |
| --- | --- | --- |
| First rubrics (6 verdicts) | 5 of 6 | Failed a `remote` answer for not covering "all six postings" |
| `unlimited-pto`, first rubric (2) | 0 of 2 | Failed both for mentioning Lorum, though both called it only "flexible" |
| Giga rubric with "1-3 years" (6 re-judges) | 5 of 6 | Failed one "1+ years" answer and passed an identical one |
| Final rubrics (8) | 8 of 8 | One lenient pass: a `remote` answer that only implied none are remote |

Every disagreement came from the rubric: the judge treated any name or fact in
it as something the answer had to cover. Telling the judge not to do that
didn't help; rewriting the rubric to state only what passes and what fails
did. With `unlimited-pto`'s final rubric, it passed an answer that set Lorum
apart as "not explicitly unlimited" and failed one that listed Lorum under
"postings that offer unlimited PTO", which is what I'd have done.

### Flaky cases

- **`edra-interviews`**: failed 3 times (baseline run 1 of the first round,
  `min-years`, and 1 of 3 targeted runs), always by answering without a tool.
  Stable after `tool-first` (6 of 6).
- **`visa`**: failed 1 of 3 in the first round by inventing visa help from
  Mistral's relocation support. It passed every run after that, so it may
  still be flaky at a lower rate.
- **Cost and steps** varied more than results. `remote` ran $0.011–0.017,
  `hazel-pto` 3–5 steps and $0.008–0.022, `300k-in-office` 2–4 steps and
  $0.007–0.016, and `edra-interviews` 3–5 steps, all with the same result.

### Not done: a bigger model

I skipped the Sonnet comparison. `AGENT_MODEL=claude-sonnet-5-5` runs it, at
twice Haiku's per-token price plus thinking tokens, so roughly $0.35–0.60 a
run. Two limits would need checking first: `MAX_COST_PER_TURN` ($0.05) could
stop expensive cases, and `max_tokens=4000` includes thinking.
