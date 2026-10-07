# LLM Practice

Hands-on exercises for building and reinforcing my fundamentals with large language models.

Each practice task lives in its own folder with its own README describing the goal, approach, and what I learned.

## Tasks

| # | Task | Topic | Status |
|---|------|-------|--------|
| 01 | [Chat](01-chat/) | Multi-turn chat: conversation history, token usage, temperature, cost | Done |
| 02 | [Extraction](02-extraction/) | Structured extraction: Pydantic validation, JSON in the prompt vs. forced tool call, data quality | Done |
| 03 | [Tools](03-tools/) | Tool use: Postgres database, narrow query tools, tool loop agent, parameterized queries | Done |
| 04 | [RAG](04-rag/) | Retrieval-augmented generation: chunking, embeddings with pgvector, cited answers, semantic vs. keyword search | Done |

## Structure

```
llm-practice/
├── 01-task-name/
│   ├── README.md   # goal, approach, takeaways
│   └── ...         # code, notebooks, notes
├── 02-task-name/
└── ...
```
