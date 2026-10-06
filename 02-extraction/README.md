# Exercise 2: Structured extraction

Goal: turn 11 real job postings (plain text) into validated `JobPosting`
objects with Pydantic, and compare ways of getting reliable JSON from an LLM.

Model: Claude Haiku 4.5 ($1 / $5 per million input / output tokens)

## Approach A: ask for JSON in the prompt

I put the Pydantic schema (`JobPosting.model_json_schema()`) in the system
prompt, told the model to return only JSON, validated the reply with
`model_validate_json`, and retried up to 2 times with the validation error.

### What happened

Every reply came back wrapped in markdown code fences (```json ... ```),
so validation failed on the first character. The JSON inside was valid.
Retrying with the error message didn't help because the model repeated the same
format and only dropped the fences on the third attempt. The error
never said what was wrong with the format.

The fences come from the model's training for chat interfaces, where
markdown is rendered. "Return ONLY JSON" didn't rule them out because the
model treats fences as formatting, not extra text.

### Fix

I added `strip_fences()` to remove the wrapper before validating. The
model's output didn't change just that my code got better at handling it.

| | Before | After `strip_fences` |
| --- | --- | --- |
| Valid on first try | 0/11 | 11/11 |
| Total cost | $0.086 | $0.025 |

Failed attempts tripled the cost, since each retry resends the full
posting plus the failed reply.

### Data quality

The structure was valid, but the contents had problems:

- Inconsistent skill names: Postgres vs. PostgreSQL, Typescript vs.
  TypeScript, ML ops vs. MLOps, Golang vs. Go
- Vague "skills" like "Backend development" and "Developer Experience",
  and integrations listed as skills (Shopify, Klaviyo for Hazel)
- Inconsistent formats: "New York" vs. "New York, NY"

Valid JSON doesn't mean good data. Tighter field descriptions, or a fixed
list of allowed skill names, should help.

### Consistency between runs

I ran approach A twice on the same 11 postings and compared the results.
I checked the values against the posting text and found no invented
values in either run.

Fields with one clear answer were identical both times: company, title,
location, years of experience, salary, and `ai_company`.

The skill lists changed, even though the input was exactly the same:

- Bevel dropped "Scalability", "Security", and "Testing"
- Giga dropped "SQL" and "Slack integration" and added the vague
  "Software engineering"
- Lorum merged "AWS" and "GCP" into "AWS/GCP" and dropped
  "Message queues" and "Stream processing"

Open-ended fields involve judgment about what to include, so the model's
randomness shows up there. Counting skill frequencies across postings
would give different numbers on each run.

Possible fixes: set temperature to 0 for more repeatable runs, or give the
model a fixed list of allowed skill names to choose from, which would also
fix the inconsistent naming.


## Approach B: force a tool call

I defined a tool, `record_job_posting`, with the `JobPosting` schema as its
input, and used `tool_choice` to force the model to call it. Nothing
actually runs; the tool is just a form the model fills in. My code reads
the data from `block.input` (already a Python dict) and validates it with
`JobPosting.model_validate`. The system prompt no longer needs the schema
or JSON instructions.

### Results

| | Approach A (with `strip_fences`) | Approach B |
| --- | --- | --- |
| Valid on first try | 11/11 | 11/11 |
| Cleanup code needed | `strip_fences` | None |
| Total cost | $0.025 | $0.033 |

B costs about 30% more because the tool definition is sent with every
request, and the API adds hidden system instructions for tool use. It
never needed retries, though, and A cost $0.086 before I added
`strip_fences`.

### Data quality

The factual fields (company, title, location, years, salary,
`ai_company`) were identical to approach A.

The skill lists still had problems:

- Inconsistent naming: mostly Title Case ("ML Ops", "Backend Systems"),
  but OpenAI's list was all lowercase and Sola's was mixed
- Omissions: Mistral's posting lists Prometheus, Grafana, and Datadog,
  but B left them out (approach A included them)
- [Giga: describe what you found when you checked giga.txt for "Python"]
- Improvements: Hazel's integrations were labeled as integrations
  ("Shopify integrations") instead of looking like skills

The tool controls the format of the output, but changing how you ask
still shifts the content a little.

### Lessons

- Asking a model for a format isn't a guarantee. Small cleanup code around
  its output is often cheaper and more reliable than retrying.
- Retries are expensive and only help if the error tells the model what to
  change.
- Cleanup code only fixes problems you anticipated. Approach B (forced tool
  call) should remove the problem at its source.
- Factual fields (names, numbers) are stable across runs; open-ended fields
  (lists, judgments) vary. Run important extractions more than once, or
  constrain the output.
- Tool calling can be used for structured output: the "tool" doesn't run,
  it's a form the model fills in, and my code gets a ready-made dict.
- Reliable format isn't the same as correct content. B never failed
  validation, but it still omitted values and named skills inconsistently.
- Every tool adds input tokens to every request (its definition plus
  hidden tool-use instructions), even when it's the only tool. Agents
  with many tools pay for all of them on every call.
- Changing how you ask for output can change the content, not just the
  format. Compare approaches on the same data instead of assuming they're
  equivalent.


## Conclusion

Forcing a tool call reliably returns the right structure with no cleanup
code, so it's the better default, even at a slightly higher cost. Neither
approach guarantees correct content: both had inconsistent skill names,
and B omitted values that A included. Better content needs tighter field
descriptions, a fixed list of allowed values, or evals that check the
results.