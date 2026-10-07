"""Exercise 3, step 4: a tool loop that answers questions from the job search database."""
import json

from anthropic import Anthropic, APIError
from dotenv import load_dotenv

from tools import TOOLS, get_applications, get_posting, search_postings

load_dotenv()
client = Anthropic()

MODEL = "claude-haiku-4-5-20251001"
INPUT_PRICE_PER_MTOK = 1.00
OUTPUT_PRICE_PER_MTOK = 5.00
MAX_ROUNDS = 10

SYSTEM = (
    "You help the user with their job search. Answer from their database using "
    "the tools. Don't guess postings, salaries, or application statuses. Don't mention tool names to the user."
)

# The only functions the model can reach, keyed by the tool names in TOOLS.
TOOL_FUNCTIONS = {
    "search_postings": search_postings,
    "get_posting": get_posting,
    "get_applications": get_applications,
}


def cost_of(usage) -> float:
    return (usage.input_tokens * INPUT_PRICE_PER_MTOK
            + usage.output_tokens * OUTPUT_PRICE_PER_MTOK) / 1_000_000


def run_tool(block) -> dict:
    """Run one tool_use block and return the matching tool_result block."""
    fn = TOOL_FUNCTIONS.get(block.name)
    if fn is None:
        content, is_error = f"Unknown tool: {block.name}", True
    else:
        try:
            result = fn(**block.input)
            content = json.dumps(result)
            # The functions report problems like a missing posting as {"error": ...}.
            is_error = isinstance(result, dict) and "error" in result
        except Exception as e:
            content, is_error = f"{type(e).__name__}: {e}", True

    print(f"  -> {block.name}({json.dumps(block.input)})"
          f"{' ERROR' if is_error else ''}: {content[:120]}")
    return {"type": "tool_result", "tool_use_id": block.id,
            "content": content, "is_error": is_error}


def ask(question: str) -> str:
    """Answer one question, calling tools until the model stops asking for them."""
    messages = [{"role": "user", "content": question}]
    total_cost = 0.0

    for round_num in range(1, MAX_ROUNDS + 1):
        resp = client.messages.create(model=MODEL, max_tokens=4000, system=SYSTEM,
                                      tools=TOOLS, messages=messages)
        cost = cost_of(resp.usage)
        total_cost += cost
        print(f"round {round_num}: {resp.stop_reason}, {resp.usage.input_tokens} in / "
              f"{resp.usage.output_tokens} out, ${cost:.6f}")
        # Keep the whole reply, tool_use blocks included; the results below refer to their ids.
        messages.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason != "tool_use":
            print(f"total: {round_num} round(s), ${total_cost:.6f}")
            answer = "".join(b.text for b in resp.content if b.type == "text")
            if resp.stop_reason == "max_tokens":
                answer += "\n[cut off: hit max_tokens]"
            return answer or f"[no answer; stop_reason: {resp.stop_reason}]"

        # One result per tool call, all in a single user message.
        results = [run_tool(b) for b in resp.content if b.type == "tool_use"]
        messages.append({"role": "user", "content": results})

    print(f"total: {MAX_ROUNDS} rounds, ${total_cost:.6f}")
    return f"[stopped after {MAX_ROUNDS} rounds without a final answer]"


def main():
    print("Ask about your job search. Type 'quit' to exit.")
    while True:
        try:
            question = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            break  # Ctrl-D or Ctrl-C
        if question.lower() in ("quit", "exit"):
            break
        if not question:
            continue  # ignore empty lines

        # Each question starts a fresh conversation; nothing carries over.
        try:
            answer = ask(question)
        except APIError as e:
            # The SDK has already retried rate limits, server errors, and dropped connections.
            print(f"\n[API error: {type(e).__name__}: {e}]")
            continue
        except KeyboardInterrupt:
            print("\n[cancelled]")
            continue
        print(f"\nClaude: {answer}")


if __name__ == "__main__":
    main()
