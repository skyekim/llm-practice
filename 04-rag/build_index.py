"""Exercise 4, step 1: chunk each posting, embed the chunks, and store them.

Drops and recreates the chunks table, so rerunning it resets the index.
Requires the postings table from 03-tools/setup_db.py.
"""
import os
import re

import psycopg
from dotenv import load_dotenv
from pgvector.psycopg import register_vector
from sentence_transformers import SentenceTransformer

load_dotenv()

MODEL_NAME = "all-MiniLM-L6-v2"
# all-MiniLM-L6-v2 produces 384 numbers per text.
EMBEDDING_DIM = 384

DROP = "DROP TABLE IF EXISTS chunks"

SCHEMA = f"""
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE chunks (
    id          SERIAL PRIMARY KEY,
    posting_id  INTEGER NOT NULL REFERENCES postings(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    text        TEXT NOT NULL,
    embedding   vector({EMBEDDING_DIM}) NOT NULL,
    UNIQUE (posting_id, chunk_index)
);
"""

# Pieces shorter than this are headings like "Requirements"; they get merged
# into the paragraph that follows them.
MIN_CHUNK_CHARS = 50

# Chunks longer than this get split at line breaks. This keeps one-line facts like
# "Visa sponsorship" from being buried in long lists, and keeps every chunk well
# under the ~1,000 characters all-MiniLM-L6-v2 reads before cutting off.
MAX_CHUNK_CHARS = 300


def split_long(chunk: str) -> list[str]:
    """Split a chunk over MAX_CHUNK_CHARS into groups of whole lines.

    A single line longer than the limit, like a prose paragraph, is kept whole.
    """
    if len(chunk) <= MAX_CHUNK_CHARS:
        return [chunk]

    parts = []
    current = ""
    for line in chunk.split("\n"):
        if not line.strip():
            continue
        candidate = f"{current}\n{line}" if current else line
        # Keep adding while current is still heading-sized, so a heading stays
        # with the paragraph after it.
        if len(current) >= MIN_CHUNK_CHARS and len(candidate) > MAX_CHUNK_CHARS:
            parts.append(current)
            current = line
        else:
            current = candidate

    # Don't leave a tiny leftover on its own; attach it to the previous part.
    if current:
        if parts and len(current) < MIN_CHUNK_CHARS:
            parts[-1] = f"{parts[-1]}\n{current}"
        else:
            parts.append(current)
    return parts


def chunk_text(text: str) -> list[str]:
    """Split on blank lines, merge short pieces into the next paragraph,
    then split long chunks at line breaks."""
    pieces = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    chunks = []
    pending = ""
    for piece in pieces:
        pending = f"{pending}\n\n{piece}" if pending else piece
        if len(pending) >= MIN_CHUNK_CHARS:
            chunks.append(pending)
            pending = ""

    # Short pieces at the very end have no next paragraph, so attach them to the last chunk.
    if pending:
        if chunks:
            chunks[-1] = f"{chunks[-1]}\n\n{pending}"
        else:
            chunks.append(pending)
    return [part for chunk in chunks for part in split_long(chunk)]


def main():
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        conn.execute(DROP)
        conn.execute(SCHEMA)
        # Lets psycopg send numpy arrays as vector values; needs the extension to exist first.
        register_vector(conn)

        model = SentenceTransformer(MODEL_NAME)

        postings = conn.execute("SELECT id, slug, raw_text FROM postings ORDER BY id").fetchall()
        for posting_id, slug, raw_text in postings:
            chunks = chunk_text(raw_text)
            embeddings = model.encode(chunks)  # one row of 384 numbers per chunk

            with conn.cursor() as cur:
                cur.executemany(
                    """INSERT INTO chunks (posting_id, chunk_index, text, embedding)
                       VALUES (%s, %s, %s, %s)""",
                    [(posting_id, i, chunk, embedding)
                     for i, (chunk, embedding) in enumerate(zip(chunks, embeddings))],
                )
            print(f"{slug}: {len(chunks)} chunks")

        count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        print(f"chunks: {count} rows")


if __name__ == "__main__":
    main()
