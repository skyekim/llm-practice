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