# 01 – Chat

A simple multi-turn chat loop against the Claude API, used to explore conversation history, token usage, temperature, and cost.

## Questions and Answers

### 1. Why does the model "remember" earlier messages, and what happens without the history?

The API is stateless. The model doesn't remember anything between requests. It only seems to remember because my code keeps a `messages` list and resends the whole conversation with every request.

When I stopped appending the model's replies, it still knew my name because my messages were still sent, but it couldn't see its own earlier answers. So it re-answered every previous question each turn and kept greeting me as if the conversation had just started.

### 2. How did input tokens change over a conversation, and why?

Input tokens grew every turn (12 → 44 → 127 → 226) because each request includes the full history. This included the system prompt, all my previous messages, and all of the model's previous replies.

Each turn's input was roughly the previous input, plus the previous reply, plus my new message. That's why long conversations get more expensive, even when new messages are short.

### 3. What does temperature do?

Temperature controls randomness. At 0, I got the same cafe name every time. At 1, the answers varied, but they stayed similar ("Brew" showed up almost every time), so temperature adds randomness but not real creativity. Changing the prompt has a bigger effect.

Also, the current Python SDK (v1.0) removed the `temperature` parameter, so I had to pass it with `extra_body`, and newer models ignore it.

### 4. How much did it cost?

Each turn cost about $0.0003, and a two-turn session cost about $0.0007. Output tokens cost 5× as much as input on Haiku 4.5 ($1 vs. $5 per million tokens), so long replies drive cost more than long questions, until the conversation history grows large.
