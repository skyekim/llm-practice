"""Exercise 5, step 4: long-term memory, one summary saved per session."""
from db import connect


def ensure_table():
    """Create the memories table the first time the agent runs."""
    with connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id         SERIAL PRIMARY KEY,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                summary    TEXT NOT NULL
            )
        """)


def load_recent(n=3):
    """Return the n most recent memories, oldest first, so newer ones read last."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, created_at, summary FROM memories ORDER BY created_at DESC, id DESC LIMIT %s",
            (n,),
        ).fetchall()
    return list(reversed(rows))


def save(summary):
    with connect() as conn:
        conn.execute("INSERT INTO memories (summary) VALUES (%s)", (summary,))
