"""Exercise 1, step 1: stream a single reply from Claude."""
from dotenv import load_dotenv
from anthropic import Anthropic
from datetime import date

load_dotenv()  # reads ANTHROPIC_API_KEY from .env
client = Anthropic()

MODEL = "claude-haiku-4-5-20251001"
INPUT_PRICE_PER_MTOK = 1.00
OUTPUT_PRICE_PER_MTOK = 5.00
# SYSTEM = f"Today's date is {date.today().isoformat()}."
SYSTEM = "You are a concise tutor who answers in two sentences"

messages = []
total_cost = 0

while True:
    user_input = input("\nYou: ").strip()
    if user_input.lower() in ("quit", "exit"):
        messages.append({"role": "user", "content": user_input})
        break
    if not user_input:
        continue  # ignore empty lines

    messages.append({"role": "user", "content": user_input})
 
    print("Claude: ", end="")

    with client.messages.stream(model=MODEL, max_tokens=500, messages=messages, system=SYSTEM, extra_body={"temperature": 1}) as stream:
        for text in stream.text_stream:
            print(text, end="", flush=True)
        final = stream.get_final_message()
 
    # Save the reply so the model sees its own answers next turn
    messages.append({"role": "assistant", "content": final.content[0].text})

    cost = (final.usage.input_tokens * INPUT_PRICE_PER_MTOK + final.usage.output_tokens * OUTPUT_PRICE_PER_MTOK) / 1_000_000
    total_cost += cost
    print(f"\n[input tokens: {final.usage.input_tokens}, output tokens: {final.usage.output_tokens}]")
    print(f"[turn: ${cost:.6f} | session total: ${total_cost:.6f}]")