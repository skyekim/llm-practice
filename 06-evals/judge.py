"""Exercise 6, step 4: an LLM judge for answers string checks can't grade.

A second API call grades the agent's answer against the case's rubric. Like
exercise 2's approach B, it forces a tool call, so the verdict always comes
back as {"pass": bool, "reason": str} instead of free text to parse.
"""
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()
client = Anthropic(timeout=30)

MODEL = "claude-haiku-4-5-20251001"
INPUT_PRICE_PER_MTOK = 1.00
OUTPUT_PRICE_PER_MTOK = 5.00

SYSTEM = (
    "You grade answers from a job search assistant. The rubric lists the facts "
    "from the job postings and what a passing answer must do. Grade only against "
    "the rubric, not your own knowledge of these companies. Extra details are "
    "fine unless they contradict the rubric or the rubric forbids them. Fail the "
    "answer if it gets a rubric fact wrong, leaves out something the rubric "
    "requires, or states something the rubric says the data doesn't contain. "
    "Don't require anything the rubric doesn't ask for; the facts are there to "
    "check the answer against, not a list it must cover."
)

# reason comes before pass so the model explains its grade before deciding it.
TOOL = {
    "name": "record_verdict",
    "description": "Record whether the answer passes the rubric, and why.",
    "input_schema": {
        "type": "object",
        "properties": {
            "reason": {"type": "string",
                       "description": "One or two sentences naming what the answer got right or wrong"},
            "pass": {"type": "boolean"},
        },
        "required": ["reason", "pass"],
    },
}


def cost_of(usage) -> float:
    return (usage.input_tokens * INPUT_PRICE_PER_MTOK
            + usage.output_tokens * OUTPUT_PRICE_PER_MTOK) / 1_000_000


def judge(question: str, answer: str, rubric: str) -> dict:
    """Grade answer against rubric. Returns {"pass": bool, "reason": str, "cost": float}."""
    prompt = (f"<question>\n{question}\n</question>\n\n"
              f"<rubric>\n{rubric}\n</rubric>\n\n"
              f"<answer>\n{answer}\n</answer>")
    resp = client.messages.create(model=MODEL, max_tokens=500, system=SYSTEM,
                                  messages=[{"role": "user", "content": prompt}],
                                  tools=[TOOL],
                                  tool_choice={"type": "tool", "name": "record_verdict"})
    verdict = next(b for b in resp.content if b.type == "tool_use").input
    return {"pass": verdict["pass"], "reason": verdict["reason"],
            "cost": cost_of(resp.usage)}
