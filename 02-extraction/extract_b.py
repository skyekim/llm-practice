"""Exercise 2, approach B: force a tool call to get structured output."""
import json
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError

load_dotenv()
client = Anthropic()

MODEL = "claude-haiku-4-5-20251001"
INPUT_PRICE_PER_MTOK = 1.00
OUTPUT_PRICE_PER_MTOK = 5.00

POSTINGS_DIR = Path(__file__).parent / "postings"
RESULTS_FILE = Path(__file__).parent / "results_b.json"


class JobPosting(BaseModel):
    company: str
    title: str
    location: str | None = Field(description="City, or null if not stated")
    min_years: int | None = Field(description="Minimum years of experience, or null if not stated")
    skills: list[str] = Field(description="Technical skills mentioned")
    ai_company: bool = Field(description="True if the product is AI-focused")
    salary_min: int | None = Field(description="Minimum annual salary in USD, or null if not stated")
    salary_max: int | None = Field(description="Maximum annual salary in USD, or null if not stated")


SYSTEM = (
    "Extract the job posting details. Use null for anything the posting does not state. Do not guess."
)

TOOL = {"name": "record_job_posting",
           "description": "Record the extracted details of a job posting.",
           "input_schema": JobPosting.model_json_schema()}

def cost_of(usage) -> float:
    return (usage.input_tokens * INPUT_PRICE_PER_MTOK
            + usage.output_tokens * OUTPUT_PRICE_PER_MTOK) / 1_000_000

def extract(posting_text: str):
    """Returns (JobPosting or None, attempts used, cost)."""
    messages = [{"role": "user", "content": posting_text}]

    resp = client.messages.create(model=MODEL, max_tokens=1000,
                                  system=SYSTEM, messages=messages, tools=[TOOL],
                                  tool_choice={"type": "tool", "name": "record_job_posting"})
    cost = cost_of(resp.usage)
    block = next(b for b in resp.content if b.type == "tool_use")

    try:
        return JobPosting.model_validate(block.input), 1, cost
    except ValidationError as e:
        print(f"  validation failed: {e}")
        return None, 1, cost


def main():
    results = {}
    session_cost = 0.0
    first_try = 0

    for path in sorted(POSTINGS_DIR.glob("*.txt")):
        print(f"{path.name}:")
        posting, attempts, cost = extract(path.read_text())
        session_cost += cost

        if posting:
            first_try += attempts == 1
            results[path.stem] = posting.model_dump()
            print(f"  ok after {attempts} attempt(s), ${cost:.6f}")
        else:
            results[path.stem] = None
            print(f"  FAILED after {attempts} attempts, ${cost:.6f}")

    RESULTS_FILE.write_text(json.dumps(results, indent=2))
    print(f"\nValid on first try: {first_try}/{len(results)}")
    print(f"Total cost: ${session_cost:.6f}")
    print(f"Results saved to {RESULTS_FILE.name}")


if __name__ == "__main__":
    main()