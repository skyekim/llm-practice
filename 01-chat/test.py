from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()
client = Anthropic()
resp = client.messages.create(model="claude-haiku-4-5-20251001", max_tokens=100,
    messages=[{"role": "user", "content": "Say hello in one sentence."}])
print(resp.content[0].text)
print(resp.usage)