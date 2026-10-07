"""Exercise 4, step 5: answer questions from the retrieved chunks, with citations.

Requires the index from build_index.py.
"""
import os

import psycopg
from anthropic import Anthropic, APIError
from dotenv import load_dotenv
from pgvector.psycopg import register_vector
from sentence_transformers import SentenceTransformer

load_dotenv()
client = Anthropic()

MODEL = "claude-haiku-4-5-20251001"
INPUT_PRICE_PER_MTOK = 1.00
OUTPUT_PRICE_PER_MTOK = 5.00

# Must be the same model that embedded the chunks, or the vectors aren't comparable.
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
TOP_K = 10

SYSTEM = (
    "You answer questions about job postings. Answer only from the provided excerpts. "
    "Cite chunk IDs for each claim, like [chunk 12]. "
    "If the excerpts don't contain the answer, say so."
)

# Loaded once at startup; it takes a few seconds.
embedder = SentenceTransformer(EMBEDDING_MODEL_NAME)


def cost_of(usage) -> float:
    return (usage.input_tokens * INPUT_PRICE_PER_MTOK
            + usage.output_tokens * OUTPUT_PRICE_PER_MTOK) / 1_000_000


def retrieve(conn, question: str) -> list[tuple]:
    """Return the TOP_K closest chunks as (chunk id, company slug, similarity, text)."""
    embedding = embedder.encode(question)
    # <=> is cosine distance, so 1 - distance is cosine similarity.
    return conn.execute(
        """SELECT c.id, p.slug, 1 - (c.embedding <=> %s) AS similarity, c.text
           FROM chunks c JOIN postings p ON p.id = c.posting_id
           ORDER BY c.embedding <=> %s
           LIMIT %s""",
        (embedding, embedding, TOP_K),
    ).fetchall()


def build_prompt(question: str, chunks: list[tuple]) -> str:
    excerpts = "\n\n".join(f"[chunk {chunk_id}, {slug}]\n{text}"
                           for chunk_id, slug, _, text in chunks)
    return f"Excerpts:\n\n{excerpts}\n\nQuestion: {question}"


def ask(conn, question: str) -> str:
    chunks = retrieve(conn, question)
    # Show what was retrieved, so a bad answer can be traced to bad retrieval.
    for chunk_id, slug, similarity, text in chunks:
        print(f"  [chunk {chunk_id}, {slug}] {similarity:.3f}  {text[:60]!r}")

    resp = client.messages.create(
        model=MODEL, max_tokens=1000, system=SYSTEM,
        messages=[{"role": "user", "content": build_prompt(question, chunks)}],
    )
    print(f"  {resp.usage.input_tokens} in / {resp.usage.output_tokens} out, "
          f"${cost_of(resp.usage):.6f}")
    return "".join(b.text for b in resp.content if b.type == "text")


def main():
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        register_vector(conn)
        print("Ask about the job postings. Type 'quit' to exit.")
        while True:
            try:
                question = input("\nYou: ").strip()
            except (EOFError, KeyboardInterrupt):
                break  # Ctrl-D or Ctrl-C
            if question.lower() in ("quit", "exit"):
                break
            if not question:
                continue  # ignore empty lines

            try:
                answer = ask(conn, question)
            except APIError as e:
                # The SDK has already retried rate limits, server errors, and dropped connections.
                print(f"\n[API error: {type(e).__name__}: {e}]")
                continue
            print(f"\nClaude: {answer}")


if __name__ == "__main__":
    main()
