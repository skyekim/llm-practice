"""Exercise 5, step 5: append every step of a session to trace.jsonl.

One JSON object per line, so a session can be replayed with jq or a few lines
of Python. Rolled-back turns stay here: the trace records what happened, not
what the model remembers.
"""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Next to this file, wherever the agent is run from.
TRACE_PATH = Path(__file__).parent / "trace.jsonl"
# One process is one session, so every line it writes shares this id.
SESSION_ID = uuid.uuid4().hex[:8]


def trace(event: str, **fields):
    # The only floats are dollar costs; 6 decimals hides float noise like 0.014027999999999999.
    fields = {k: round(v, 6) if isinstance(v, float) else v for k, v in fields.items()}
    record = {"ts": datetime.now(timezone.utc).isoformat(), "session_id": SESSION_ID,
              "event": event, **fields}
    # Opened per line, so everything up to a crash or Ctrl-C is already on disk.
    # default=str covers dates and anything else json can't encode.
    with TRACE_PATH.open("a") as f:
        f.write(json.dumps(record, default=str) + "\n")
