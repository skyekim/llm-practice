# 05 – Agent

A job search agent that brings the previous exercises together: the chat
loop from exercise 1, the postings database from exercise 2, the query tools
and tool loop from exercise 3, and the posting text search from exercise 4.

- `db.py`: the shared database connection
- `tools.py`: every tool and its definition: `search_postings` (now with a
  `company` filter), `get_posting`, `get_applications`, `search_posting_text`,
  and `update_application`, the one tool that writes
- `agent.py`: the agent. The outer loop reads my message, the inner loop calls
  Claude Haiku 4.5 and runs tools until it answers, and one `messages` list
  holds the whole session. It has step, cost, and time limits, asks y/n before
  `update_application`, and rolls back any turn that fails.
- `memory.py`: a `memories` table. When I quit, the model summarizes the
  session, and the last 3 summaries go into the next session's system prompt.
- `tracing.py`: appends every step to `trace.jsonl` (ignored by git)

Run it from the repo root with `python 05-agent/agent.py`.

## Questions and Answers

### 1. How did the agent decide between structured search and text search?

The system prompt says to use `search_postings` for structured filters like
skills and salary and `search_posting_text` for anything else, and the tool
descriptions repeat it. The model followed this well:

| Question | Tools called |
| --- | --- |
| Postings with Python paying over 200k | `search_postings(skill="python", min_salary=200000)` |
| Which of those sponsor visas? | `search_posting_text("visa sponsorship", posting_id=...)`, once for each of the 3 postings from the previous answer |
| Which postings sponsor visas? | `search_posting_text("visa sponsorship")` across every posting |
| What's the parental leave at Bevel? | Find Bevel's id, then `search_posting_text("parental leave", posting_id=1)` |

It combined them on its own: structured search to find the postings, then
text search limited to those postings.

It made three kinds of mistakes:

- **No tool for the lookup it needed.** Before I added the `company` filter,
  "parental leave at Brevel" (my typo) got "I don't have any postings from
  Brevel" with no tool call at all. Once I told it to check before saying
  something isn't there, it listed every posting by calling `search_postings`
  twice, with `ai_company` true and then false, to find Bevel. The `company`
  filter made that one call.
- **The wrong tool for the question.** Asked whether Sola sponsors visas, it
  called `get_posting`, whose structured fields never include visa
  information. It did this because its previous answer had offered to "get
  the complete posting details".
- **Preferences used in commentary but not as filters.** It remembered I
  wanted $200k+, but searched `skill="python"` without `min_salary` and
  mentioned the salary only in its summary of the results.

### 2. Which safety rails were triggered, and when?

In normal use, no limit was ever hit. The most expensive question cost
$0.0199 and the most rounds any question needed was 3, well under $0.05 and
10. I triggered each one deliberately:

| Rail | How I triggered it | What happened |
| --- | --- | --- |
| Cost limit ($0.05) | Set it to $0.001 | Stopped after round 1, before the tool ran, and told me |
| Step limit (10 rounds) | Set it to 1 | Stopped after round 1 and told me, but only after the tool had already run |
| Timeout (30 s) | Set it to 0.01 s | `APITimeoutError` after the SDK's retries, and the next question still worked |
| Tool errors | Unknown status, bad date, posting 999 | Each came back as `{"error": ...}` with `is_error: true` instead of a crash |
| Confirmation | Every `update_application` call | Showed the posting, its current status, and the change, then asked y/n |

Two rails needed fixes after they triggered:

- **Confirmation.** The tool description said "the user is asked to confirm
  first", so the model asked "Is that correct?" in chat and then the y/n
  prompt asked again. When I answered n, it retried the same call, then told
  me "I'm getting an error… this might be a system issue". The decline came
  back as `is_error: true`, and I had just said yes in chat, so it assumed
  something had broken. After I reworded the description and the decline
  message ("This is not a system error. Don't retry"), it went straight to
  the y/n prompt, didn't retry, and said I had declined.
- **Rollback.** Any failed turn (an error, Ctrl-C, or a limit) is removed from
  `messages`. Otherwise a `tool_use` without its `tool_result` makes every
  later request fail. The token counts confirmed it: after a cancelled turn,
  the next question started at 3,654 input tokens, which is the previous
  turn's 3,596 in + 48 out plus the new question. The trace later showed that
  cancelled turns weren't being added to the session cost, which I also fixed.

### 3. How did memory work, and what went wrong with it?

The basic loop worked. I said "I only want remote jobs" and quit, and the
next session knew it. I said "actually I'm fine with NYC on-site", and the
summary came out as `Changed: Open to both remote jobs and NYC on-site
positions (previously wanted only remote)`. The session after that used the
newer preference. The "Changed:" format also survived the oldest memory
dropping out: after three more sessions, the original "only remote" memory
was no longer loaded, but the answer was still right because the change
restated it.

What went wrong:

- **It claimed something it can't do.** It told me "I've updated my memory",
  but memory is only saved when I quit, and the model has no tool for it. I
  added a line explaining how memory works, and it then said "I'll remember
  that".
- **Instructions that conflicted.** "Answer only from tool results" clashed
  with answering from memory, so it hedged: "I don't have information about
  what kind of jobs you're looking for… However, I can see from our previous
  session…". Telling it to use memories for my preferences and the tools for
  postings fixed it.
- **Preferences fall off silently.** Each session saves only what's new, so
  each preference lives in its own memory. Since only the last 3 load, one
  more session will push out the remote/NYC memory, and the agent won't say
  it forgot. Rewriting a full profile each session would fix this, but then a
  mistake in one summary would be copied forward.
- **Outdated memories.** The prompt says to trust the database over memory,
  and to trust newer memories over older ones. That handles application
  statuses, but not a preference I change without mentioning it.

Memory is cheap but constant. The same question took 1,865 input tokens with
1 memory and 1,896 with 2, so about 30 tokens per short memory. That's added
to every request, including each tool round. The summary call at quit resends
the whole session, so it costs about as much as one more round: 2,116 to
4,270 input tokens, or $0.002 to $0.004.

### 4. What did a typical multi-step question cost, compared with a simple one?

| Question | Rounds | Input tokens (last round) | Cost |
| --- | --- | --- | --- |
| "What is the highest salary" (answered from history) | 1 | 3,596 | $0.0038 |
| Python over 200k (one search) | 2 | 1,618 | $0.0041 |
| Parental leave at Brevel, first question of a session | 3 | 3,462 | $0.0088 |
| Which of those sponsor visas? (3 text searches) | 2 | 5,082 | $0.0082 |
| Parental leave at Bevel, 5th question of a session | 3 | 7,204 | $0.0199 |

A simple question with one tool cost about $0.004, and a multi-step question
about $0.008 to $0.02. The number of steps mattered less than how much was in
the history. The same parental leave question cost $0.0088 as a session's
first question and $0.0199 as its fifth, because each round resends
everything before it. Text search results are the biggest cost: the three
visa searches added 30 chunks and took input from 1,618 to 5,082 tokens, and
those chunks were resent with every later request. A 5-question session cost
$0.049 in total.

### 5. What would you need to change before letting other people use this agent?

- **Separate users.** The database has one set of applications and one set
  of memories. Each needs a user id, and every query and tool needs to filter
  by it.
- **A real interface for confirmation.** The y/n prompt uses the terminal's
  `input()`. A web or chat version needs a confirm button, and the agent must
  wait for it.
- **Prompt injection.** Posting text goes straight into the model, and the
  model can call a tool that writes. A posting could contain instructions.
  Confirmation protects writes today, but a user could approve an action
  without reading it.
- **Private data in traces.** `trace.jsonl` holds every chat, posting excerpt,
  and application note. Before sharing it would need limited access, a
  retention period, and possibly redaction.
- **Spending limits per user.** $0.05 per question doesn't stop someone from
  asking thousands of questions. It needs daily or monthly limits per user.
- **Limiting history.** Cost grows with every turn. Long sessions need old tool
  results shortened or the history summarized.
- **Memory people can see and edit.** They should be able to view, correct,
  and delete what the agent remembers, since it can be outdated or wrong.
- **Evaluation.** Every prompt fix here came from a mistake I noticed by
  hand. Before changing prompts for other people, I'd want a set of test
  questions with expected tool calls and answers, run on every change. That's
  the tracing and evaluation work in exercise 7.
