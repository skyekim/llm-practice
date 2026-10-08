"""Exercise 5, steps 2-5: a chat loop around the tool loop, keeping one history
for the session, with step, cost, and time limits, confirmation before any
tool that changes data, a summary of each session remembered in the next, and
every step logged to trace.jsonl.

Exercise 6, step 1: the tool loop is run_agent(), callable from code. By
default it runs without memory and denies every write, so evals can't change
the applications table; the chat in main() is a thin wrapper around it.
"""
import json
import os
import time
from datetime import date

from anthropic import Anthropic, APIError
from dotenv import load_dotenv

import memory
from tools import TOOLS, TOOL_FUNCTIONS, get_posting
from tracing import TRACE_PATH, SESSION_ID, trace

load_dotenv()
client = Anthropic(timeout=30)

# (input, output) USD per million tokens. AGENT_MODEL picks another model
# without editing this file, e.g. to compare a bigger one in the evals.
PRICES_PER_MTOK = {
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    "claude-sonnet-5-5": (2.00, 10.00),
}
MODEL = os.environ.get("AGENT_MODEL", "claude-haiku-4-5-20251001")
INPUT_PRICE_PER_MTOK, OUTPUT_PRICE_PER_MTOK = PRICES_PER_MTOK[MODEL]
MAX_ROUNDS = 10
MAX_COST_PER_TURN = 0.05
# Tools that change data; the user confirms each call before it runs.
CONFIRM_TOOLS = {"update_application"}
MEMORIES_LOADED = 3

BASE_SYSTEM = (
    f"Today's date is {date.today().isoformat()}. "
    "You help me with my job search. Use search_postings for structured filters "
    "like skills and salary, and search_posting_text for anything else in the "
    "posting text. Answer only from tool results, and say so when the data "
    "doesn't contain an answer. When a claim comes from search_posting_text, "
    "cite its chunk id, like [chunk 12]. "
    "You don't know which companies are in my saved postings until you search, "
    "so a company name you don't recognize may still be there. Never answer a "
    "question about a company, posting, or application without calling a tool "
    "first; to check a company, call search_postings with its name. "
    "Only call update_application when I tell you something changed, never on "
    "your own; if it's unclear which posting I mean, ask me first."
)

SUMMARY_PROMPT = (
    "This session is ending. Summarize what's worth remembering for future "
    "sessions in at most 5 short bullet points: my preferences, decisions, and "
    "what I applied to or changed. Include only what's new in this session, not "
    "what you already remembered. If I changed my mind about something you "
    "remembered, write it as 'Changed: ...' so the old memory is overridden. "
    "Reply with only the bullet points, or 'Nothing new' if there's nothing to remember."
)


def build_system(memories: list) -> str:
    """BASE_SYSTEM plus the remembered summaries, oldest first, each with its date."""
    if not memories:
        return BASE_SYSTEM
    sections = "\n\n".join(f"Session on {m['created_at'].date().isoformat()}:\n{m['summary']}"
                           for m in memories)
    return (
        f"{BASE_SYSTEM}\n\n"
        "What you remember from previous sessions (oldest first). Use these to "
        "answer questions about my preferences and past decisions; postings and "
        "applications still come from the tools. If memories conflict, the newer "
        "one wins. If a memory conflicts with tool results, trust the tools; the "
        "database is always current. You can't save memories yourself: a summary "
        "of this session is saved automatically when it ends, so say you'll "
        "remember something, not that you've updated your memory.\n\n"
        f"{sections}"
    )


class TurnStopped(Exception):
    """A limit stopped the turn before the model gave a final answer."""


def cost_of(usage) -> float:
    return (usage.input_tokens * INPUT_PRICE_PER_MTOK
            + usage.output_tokens * OUTPUT_PRICE_PER_MTOK) / 1_000_000


def deny_all(block) -> bool:
    """The default for run_agent: every CONFIRM_TOOLS call is declined, so
    nothing is written, but the attempt still shows up in tool_calls."""
    return False


def confirm(block) -> bool:
    """Show the change a CONFIRM_TOOLS call would make and ask the user y/n."""
    args = dict(block.input)
    # Name the posting, since picking the wrong one is the likeliest mistake.
    posting = get_posting(args.pop("posting_id", None))
    if "error" in posting:
        target = "unknown posting"  # the tool itself will report the error
    else:
        current = posting["application"]["status"] if posting["application"] else "none"
        target = f"{posting['company']} - {posting['title']} (current status: {current})"
    print(f"\n  {block.name}: {target}")
    for key, value in args.items():
        print(f"    {key}: {value}")
    try:
        return input("  Run this? [y/n] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def run_tool(block, turn: int, approve, tool_calls: list) -> dict:
    """Run one tool_use block, record it in tool_calls, and return the matching
    tool_result block. approve(block) decides whether a CONFIRM_TOOLS call runs."""
    fn = TOOL_FUNCTIONS.get(block.name)
    confirmed = None  # True or False only for CONFIRM_TOOLS
    duration_ms = None  # time in the tool itself, not waiting for y/n
    if fn is None:
        content, is_error = f"Unknown tool: {block.name}", True
    else:
        try:
            if block.name in CONFIRM_TOOLS:
                confirmed = approve(block)
            if confirmed is False:
                content = ("The user said no at the confirmation prompt, so nothing was "
                           "updated. This is not a system error. Don't retry; tell the "
                           "user the change wasn't made.")
                is_error = True
            else:
                start = time.perf_counter()
                try:
                    result = fn(**block.input)
                finally:
                    duration_ms = round((time.perf_counter() - start) * 1000)
                content = json.dumps(result)
                # The functions report problems like a missing posting as {"error": ...}.
                is_error = isinstance(result, dict) and "error" in result
        except Exception as e:
            content, is_error = f"{type(e).__name__}: {e}", True

    took = f" ({duration_ms} ms)" if duration_ms is not None else ""
    print(f"  -> {block.name}({json.dumps(block.input)}){took}"
          f"{' ERROR' if is_error else ''}: {content[:120]}")
    # The full result, exactly as the model sees it, not the preview above.
    trace("tool_call", turn=turn, tool_use_id=block.id, name=block.name,
          input=block.input, result=content, is_error=is_error,
          duration_ms=duration_ms, confirmed=confirmed)
    tool_calls.append({"name": block.name, "input": block.input, "result": content,
                       "is_error": is_error, "confirmed": confirmed})
    return {"type": "tool_result", "tool_use_id": block.id,
            "content": content, "is_error": is_error}


def ask(messages: list, system: str, turn: int, approve, run: dict) -> str:
    """Answer the last question in messages, calling tools until the model stops
    asking for them. Appends every reply and tool result to messages, and
    keeps run's steps, cost, and tool_calls up to date as it goes, so they're
    right even when this raises.

    Returns the answer. Raises TurnStopped if MAX_ROUNDS or MAX_COST_PER_TURN
    runs out first.
    """
    for round_num in range(1, MAX_ROUNDS + 1):
        resp = client.messages.create(model=MODEL, max_tokens=4000, system=system,
                                      tools=TOOLS, messages=messages)
        cost = cost_of(resp.usage)
        run["steps"] = round_num
        run["cost"] += cost
        print(f"round {round_num}: {resp.stop_reason}, {resp.usage.input_tokens} in / "
              f"{resp.usage.output_tokens} out, ${cost:.6f}")
        trace("model_response", turn=turn, round=round_num, stop_reason=resp.stop_reason,
              input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens,
              cost=cost, content=[b.model_dump() for b in resp.content])
        # Keep the whole reply, tool_use blocks included; the results below refer to their ids.
        messages.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason != "tool_use":
            print(f"total: {round_num} round(s), ${run['cost']:.6f}")
            answer = "".join(b.text for b in resp.content if b.type == "text")
            if resp.stop_reason == "max_tokens":
                answer += "\n[cut off: hit max_tokens]"
            return answer or f"[no answer; stop_reason: {resp.stop_reason}]"

        # Checked after each call, so a turn can overshoot by up to one round.
        # A final answer is kept even if it went over, since it's already paid for.
        if run["cost"] > MAX_COST_PER_TURN:
            print(f"total: {round_num} round(s), ${run['cost']:.6f}")
            raise TurnStopped(f"stopped at ${run['cost']:.4f}, over the "
                              f"${MAX_COST_PER_TURN:.2f} limit per question")

        # One result per tool call, all in a single user message.
        results = [run_tool(b, turn, approve, run["tool_calls"])
                   for b in resp.content if b.type == "tool_use"]
        messages.append({"role": "user", "content": results})

    print(f"total: {MAX_ROUNDS} rounds, ${run['cost']:.6f}")
    raise TurnStopped(f"stopped after {MAX_ROUNDS} rounds without a final answer")


def run_agent(question: str, messages: list = None, system: str = BASE_SYSTEM,
              approve=deny_all, turn: int = 1) -> dict:
    """Answer one question and return what happened:

        {"answer": str or None, "outcome": "answer" | "stopped" | "api_error" | "cancelled",
         "error": str or None, "tool_calls": [{name, input, result, is_error, confirmed}],
         "steps": model calls, "cost": dollars, "seconds": wall time}

    The defaults are for evals: a fresh history, no memories in the system
    prompt, and every write denied. The chat passes its own history, its
    system prompt with memories, and confirm() to ask y/n.

    On success the question and everything after it stay in messages. On
    failure they're removed, so the history never ends with a dangling
    question or a tool_use that has no tool_result.
    """
    if messages is None:
        messages = []
    n = len(messages)
    messages.append({"role": "user", "content": question})
    trace("user_message", turn=turn, text=question)

    run = {"answer": None, "outcome": "answer", "error": None,
           "tool_calls": [], "steps": 0, "cost": 0.0, "seconds": 0.0}
    start = time.perf_counter()
    try:
        run["answer"] = ask(messages, system, turn, approve, run)
    except TurnStopped as e:
        run["outcome"], run["error"] = "stopped", str(e)
    except APIError as e:
        # Includes APITimeoutError. The SDK has already retried rate limits,
        # server errors, timeouts, and dropped connections.
        run["outcome"], run["error"] = "api_error", f"API error: {type(e).__name__}: {e}"
    except KeyboardInterrupt:
        run["outcome"], run["error"] = "cancelled", "cancelled"
    run["seconds"] = round(time.perf_counter() - start, 2)

    # Rolled-back turns are still traced: the trace shows what happened,
    # messages only what the model remembers.
    if run["outcome"] != "answer":
        del messages[n:]
    trace("turn_end", turn=turn, outcome=run["outcome"], answer=run["answer"],
          reason=run["error"], cost=run["cost"], steps=run["steps"], seconds=run["seconds"])
    return run


def summarize(messages: list, system: str) -> tuple[str, float]:
    """Ask the model what's worth remembering from this session. Returns (summary, cost)."""
    # The history has tool_use blocks, which the API only accepts with tools
    # defined; tool_choice "none" stops the model from calling one here.
    # Failed turns are rolled back, so messages always ends with an answer
    # and a new user message can follow.
    resp = client.messages.create(
        model=MODEL, max_tokens=300, system=system, tools=TOOLS,
        tool_choice={"type": "none"},
        messages=messages + [{"role": "user", "content": SUMMARY_PROMPT}],
    )
    cost = cost_of(resp.usage)
    print(f"summary: {resp.usage.input_tokens} in / {resp.usage.output_tokens} out, ${cost:.6f}")
    summary = "".join(b.text for b in resp.content if b.type == "text").strip()
    trace("summary", input_tokens=resp.usage.input_tokens,
          output_tokens=resp.usage.output_tokens, cost=cost, summary=summary)
    return summary, cost


def remember(messages: list, system: str) -> float:
    """Summarize the session and save it as a memory. Returns the cost."""
    if not messages:
        return 0.0  # nothing happened, so don't push a real memory out of the last few
    try:
        summary, cost = summarize(messages, system)
    except (APIError, KeyboardInterrupt) as e:
        print(f"\n[memory not saved: {type(e).__name__}]")
        trace("memory_not_saved", error=f"{type(e).__name__}: {e}")
        return 0.0
    if summary and summary.lower().rstrip(".") != "nothing new":
        memory.save(summary)
        trace("memory_saved", summary=summary)
        print(f"\nRemembered:\n{summary}")
    else:
        print("\nNothing new to remember.")
    return cost


def main():
    memory.ensure_table()
    memories = memory.load_recent(MEMORIES_LOADED)
    system = build_system(memories)
    # The full system prompt, since memories change it from one session to the next.
    trace("session_start", model=MODEL, memory_ids=[m["id"] for m in memories], system=system)
    print(f"Loaded {len(memories)} memories. Ask about your job search. Type 'quit' to exit.")
    print(f"[tracing session {SESSION_ID} to {TRACE_PATH}]")

    messages = []  # the whole session: questions, replies, tool calls, and results
    session_cost = 0.0
    turn = 0
    while True:
        try:
            question = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            break  # Ctrl-D or Ctrl-C
        if question.lower() in ("quit", "exit"):
            break
        if not question:
            continue  # ignore empty lines

        turn += 1
        result = run_agent(question, messages, system, approve=confirm, turn=turn)
        # Failed turns were still paid for.
        session_cost += result["cost"]
        if result["outcome"] == "answer":
            print(f"\nClaude: {result['answer']}")
        else:
            print(f"\n[{result['error']}]")
        print(f"[session total: ${session_cost:.6f}]")

    # Every way out of the loop (quit, Ctrl-D, Ctrl-C) ends up here.
    session_cost += remember(messages, system)
    trace("session_end", turns=turn, cost=session_cost)
    if messages:
        print(f"[session total: ${session_cost:.6f}]")


if __name__ == "__main__":
    main()
