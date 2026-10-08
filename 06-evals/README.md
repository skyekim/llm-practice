# 06 – Evals

Automated tests for the job search agent from exercise 5: a fixed set of
questions with known answers, run through the agent and graded by code.

- `../05-agent/agent.py`: the tool loop is now `run_agent(question)`, which
  returns the answer, tool calls, steps, cost, and seconds. By default it runs
  without memory and denies every `update_application` call, so evals can't
  change the applications table. The chat is a thin wrapper around it.
- `cases.json`: 20 cases in five categories (structured, text, multi-step,
  unanswerable, tricky), each with a question, `must_include` and
  `must_not_include` strings, the tools it should call, and notes on where the
  expected answer comes from
- `check_data.py`: prints the applications, skills, years, and salaries the
  expected answers rely on, to check them against the database
- `run_evals.py`: runs every case and grades it with code-based checks, then
  saves every answer and tool call to `results/<timestamp>.json`

Run it from the repo root with `python 06-evals/run_evals.py`. Pass case ids
to run only those, and `--verbose` to see the agent's rounds and tool calls.

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
