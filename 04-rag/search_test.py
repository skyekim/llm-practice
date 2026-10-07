"""Exercise 4: try a semantic search against the chunks table.

Usage: python 04-rag/search_test.py "your question here"
Requires the index from build_index.py.
"""
import os
import sys

import psycopg
from dotenv import load_dotenv
from pgvector.psycopg import register_vector
from sentence_transformers import SentenceTransformer

load_dotenv()

MODEL_NAME = "all-MiniLM-L6-v2"
TOP_K = 5


def main():
    if len(sys.argv) < 2:
        sys.exit('usage: python 04-rag/search_test.py "your question here"')
    query = " ".join(sys.argv[1:])

    # Must be the same model that embedded the chunks, or the vectors aren't comparable.
    embedding = SentenceTransformer(MODEL_NAME).encode(query)

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        register_vector(conn)
        # <=> is cosine distance, so 1 - distance is cosine similarity.
        rows = conn.execute(
            """SELECT p.slug, 1 - (c.embedding <=> %s) AS similarity, c.text
               FROM chunks c JOIN postings p ON p.id = c.posting_id
               ORDER BY c.embedding <=> %s
               LIMIT %s""",
            (embedding, embedding, TOP_K),
        ).fetchall()

    for slug, similarity, text in rows:
        print(f"\n[{slug}] {similarity:.3f}\n{text[:300]}")


if __name__ == "__main__":
    main()
