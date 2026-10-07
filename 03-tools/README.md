# 03 – Tools

A job search assistant built on the postings from exercise 2. `setup_db.py`
loads them into Postgres, `tools.py` defines three narrow query tools, and
`agent.py` runs a tool loop so Claude Haiku 4.5 can answer questions from the
database.

## Questions and Answers

### 1. How did the model choose tools, and when did it chain more than one?

The model only knows what the tool names and descriptions tell it, so the
descriptions decided which tools it called and with what arguments. 
It is important to have clear and specific names and descriptions.

- Question that used one tool and one call: "Which AI companies want Postgres?" 
  This combined both conditions into one call using `search_postings(skill="postgresql", ai_company=true)`.
- Question that made parallel calls: "Which postings want Python or Go?" This became two
  `search_postings` calls in the same reply. Each call had a separate skill, because the
  description says to call once per skill and combine the results.
- Question that performed chaining: "What skills does the job I'm interviewing for want?" 
  It took two steps. `get_applications(status="interviewing")` found Bevel's
  `posting_id`, then `get_posting(1)` got its skills. My code doesn't plan
  anything; the loop just keeps going while the model asks for tools, and
  the description told it where IDs come from.
- Working around a missing filter: questions the tools couldn't answer
  directly ("Which jobs are remote?", "What is the most common skill?")
  made it list every posting and call `get_posting` 11 times.

### 2. How did input tokens grow during multi-step questions, and why?

Every round resends the whole conversation, the same as in exercise 1. For
the Bevel question, input grew 1,126 → 1,273 → 1,493 over 3 rounds as each
tool call and its result were added to the history.

About 1,075 of those tokens are the tool definitions (plus the API's hidden
tool-use instructions), and they're paid again every round. Tool results add
up too. Yhe questions that fetched all 11 postings reached about 3,840 input
tokens in the last round and cost about $0.011. That was more than twice a typical
question. Returning `raw_text` would have made this much worse, which is why
the tools leave it out.

### 3. What happened with the counting question and the "Postgres" question?

"What is the most common skill required?" got the right headline answer,
Python, but only 1 of 8 counts was correct:

| Skill | Model said | Actual |
| --- | --- | --- |
| python | 7 | 5 |
| kubernetes | 6 | 4 |
| docker | 5 | 3 |
| postgresql | 5 | 3 |
| data pipelines | 5 | 3 |
| distributed systems | 4 | 3 |
| typescript | 4 | 4 |
| fastapi | 3 | 2 |

Every wrong count was too high, and it contradicted itself: next to "Python -
7 postings" it listed exactly the 5 correct companies. No tool counts, so it
fetched all 11 postings and counted about 126 skills in its head. Models
predict plausible text instead of keeping a tally. A `GROUP BY` query gets
this exactly right, so the fix is a narrow `count_skills` tool: let the
database count and the model explain.

For "Postgres", the model searched for `"postgresql"` because the tool
description says skills are stored as `'postgresql' (not 'postgres')`, and
it found Sola and Guac correctly. Normalizing at load time also helped the
counting question: "Postgres" and "PostgreSQL" were stored as one skill, so
it showed up as 3 postings instead of being split into 2 and 1.

### 4. What happened when a tool returned an error?

"Tell me about job posting 50" called `get_posting(50)`, which returned
`{"error": "No posting with id 50"}` marked with `is_error: true`. The model
didn't retry other IDs or make anything up. It said the posting doesn't
exist, in 2 rounds for $0.003.

It did tell me to "use `search_postings()`", which is its tool, not
something I can run, so I added "Don't mention tool names to the user" to
the system prompt.

Errors are returned as tool results instead of crashing the loop: unknown
tool names, bad arguments, missing postings, and database errors all go
back to the model so it can fix the call or explain the problem.

### 5. Why use narrow tools and parameterized queries instead of letting the model write SQL?

The model can only do what the three functions do. A request for a tool
that isn't in `TOOL_FUNCTIONS`, like `delete_postings`, gets "Unknown tool"
and nothing runs. Parameterized queries keep its input as data: searching
for the skill `x' OR 1=1 --` returned no results instead of every posting,
because the value was never treated as SQL. This matters because anything in
the conversation, including text from a posting, could try to steer the
model.

The tradeoff is flexibility. A SQL tool could have counted skills in one
query, while the narrow tools needed 12 calls and still got the counts
wrong. The answer isn't to give the model raw SQL, but to add narrow tools
for questions that keep coming up.
