"""Exercise 2, approach A: ask for JSON in the prompt, validate it, retry on errors."""
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
MAX_RETRIES = 2

POSTINGS_DIR = Path(__file__).parent / "postings"
RESULTS_FILE = Path(__file__).parent / "results_a.json"


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
    "You extract structured data from job postings.\n"
    "Return ONLY a JSON object that matches this JSON schema, with no other text:\n"
    f"{json.dumps(JobPosting.model_json_schema(), indent=2)}\n"
    "Use null for any field the posting does not state. Do not guess."
)

def strip_fences(text: str) -> str:
    """Removes the markdown code fences from the model's reply so only the JSON is left."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]      # drop the ```json line
        text = text.rsplit("```", 1)[0]    # drop the closing ```
    return text.strip()

def cost_of(usage) -> float:
    return (usage.input_tokens * INPUT_PRICE_PER_MTOK
            + usage.output_tokens * OUTPUT_PRICE_PER_MTOK) / 1_000_000

def extract(posting_text: str):
    """Returns (JobPosting or None, attempts used, cost)."""
    messages = [{"role": "user", "content": posting_text}]
    total_cost = 0.0

    for attempt in range(1, MAX_RETRIES + 2):  # first try + retries
        resp = client.messages.create(model=MODEL, max_tokens=1000,
                                      system=SYSTEM, messages=messages)
        total_cost += cost_of(resp.usage)
        text = resp.content[0].text

        try:
            return JobPosting.model_validate_json(strip_fences(text)), attempt, total_cost
        except ValidationError as e:
            print("  raw reply starts with:", repr(text[:80]))
            print(f"  attempt {attempt} failed: {e.errors()[0]['msg']}")
            # Show the model its bad output and the error, then ask again
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user", "content":
                f"Your response was not valid JSON for the schema:\n{e}\n"
                "Return ONLY the corrected JSON object, with no other text."})

    return None, MAX_RETRIES + 1, total_cost


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